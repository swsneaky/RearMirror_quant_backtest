"""
SQLite 持久化层 -- UI task queue storage.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime
from typing import Optional

from src.tasking.models import TaskRecord, TaskStatus


def _is_pid_alive(pid: int) -> bool:
    """检查给定 PID 的进程是否仍然存活 (跨平台)。"""
    if pid <= 0:
        return False
    try:
        import os as _os
        # Windows: os.kill(pid, 0) 不可用，用 ctypes 检查
        if _os.name == "nt":
            import ctypes
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        else:
            _os.kill(pid, 0)
            return True
    except (OSError, PermissionError):
        return False

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id              TEXT PRIMARY KEY,
    created_at           TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'pending',
    submit_source        TEXT NOT NULL DEFAULT 'cli',
    profile_path         TEXT,
    config_snapshot_path TEXT,
    output_dir           TEXT,
    model_name           TEXT DEFAULT '',
    universe_name        TEXT DEFAULT '',
    top_k                INTEGER DEFAULT 0,
    train_window         INTEGER DEFAULT 0,
    step                 INTEGER DEFAULT 0,
    gap                  INTEGER DEFAULT 0,
    steps                TEXT DEFAULT '',
    started_at           TEXT,
    finished_at          TEXT,
    error_message        TEXT,
    retry_of_task_id     TEXT,
    pid                  INTEGER,
    progress_pct         INTEGER DEFAULT 0,
    progress_message     TEXT DEFAULT ''
);
"""

_COLUMNS = [
    "task_id", "created_at", "status", "submit_source",
    "profile_path", "config_snapshot_path", "output_dir",
    "model_name", "universe_name", "top_k", "train_window",
    "step", "gap", "steps", "started_at", "finished_at",
    "error_message", "retry_of_task_id", "pid",
    "progress_pct", "progress_message",
]


class TaskStore:
    """线程安全的 SQLite 任务存储"""

    def __init__(self, db_path: str = "experiments/tasks.db"):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._db_path = db_path
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self._db_path, timeout=30)
            # Some Windows/E-drive environments fail when SQLite creates
            # rollback/WAL sidecar files for this lightweight task queue.
            # MEMORY journal keeps the queue persistent while avoiding those
            # sidecar-file I/O failures; the main quant DB is not affected.
            conn.execute("PRAGMA journal_mode=MEMORY")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    def _init_db(self):
        conn = self._get_conn()
        conn.execute(_CREATE_TABLE)
        conn.commit()
        # 自动迁移：为旧库添加新列
        for col, typedef in [
            ("steps", "TEXT DEFAULT ''"),
            ("progress_pct", "INTEGER DEFAULT 0"),
            ("progress_message", "TEXT DEFAULT ''"),
        ]:
            try:
                conn.execute(f"SELECT {col} FROM tasks LIMIT 1")
            except sqlite3.OperationalError:
                conn.execute(f"ALTER TABLE tasks ADD COLUMN {col} {typedef}")
                conn.commit()

    def insert(self, task: TaskRecord) -> None:
        d = task.to_dict()
        cols = ", ".join(_COLUMNS)
        placeholders = ", ".join(["?"] * len(_COLUMNS))
        values = [d.get(c) for c in _COLUMNS]
        conn = self._get_conn()
        conn.execute(f"INSERT INTO tasks ({cols}) VALUES ({placeholders})", values)
        conn.commit()

    def get(self, task_id: str) -> Optional[TaskRecord]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None:
            return None
        return TaskRecord.from_dict(dict(row))

    def update_status(
        self,
        task_id: str,
        new_status: TaskStatus,
        *,
        started_at: Optional[str] = None,
        finished_at: Optional[str] = None,
        error_message: Optional[str] = None,
        pid: Optional[int] = None,
    ) -> bool:
        conn = self._get_conn()
        sets = ["status = ?"]
        vals: list = [new_status.value]
        if started_at is not None:
            sets.append("started_at = ?")
            vals.append(started_at)
        if finished_at is not None:
            sets.append("finished_at = ?")
            vals.append(finished_at)
        if error_message is not None:
            sets.append("error_message = ?")
            vals.append(error_message)
        if pid is not None:
            sets.append("pid = ?")
            vals.append(pid)
        vals.append(task_id)
        conn.execute(
            f"UPDATE tasks SET {', '.join(sets)} WHERE task_id = ?", vals
        )
        conn.commit()
        return True

    def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        limit: int = 100,
    ) -> list[TaskRecord]:
        conn = self._get_conn()
        if status:
            rows = conn.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status.value, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [TaskRecord.from_dict(dict(r)) for r in rows]

    def claim_pending(self) -> Optional[TaskRecord]:
        """原子取一条 pending 任务并标记为 running"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT task_id FROM tasks WHERE status = 'pending' "
            "ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        now = datetime.now().isoformat()
        conn.execute(
            "UPDATE tasks SET status = 'running', started_at = ?, "
            "progress_pct = 0, progress_message = '任务启动中...' "
            "WHERE task_id = ? AND status = 'pending'",
            (now, row["task_id"]),
        )
        conn.commit()
        return self.get(row["task_id"])

    def recover_orphaned(self) -> int:
        """重启后将真正已死亡的 running 任务标记为 failed。

        安全策略：
          1. PID 已记录且进程仍存活 -> 跳过 (正常运行中)
          2. PID 未记录但启动时间 < 120 秒 -> 跳过 (子进程尚在启动宽限期)
          3. 其余情况 -> 标记为 failed
        """
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT task_id, pid, started_at FROM tasks WHERE status = 'running'"
        ).fetchall()
        if not rows:
            return 0

        now = datetime.now()
        now_str = now.isoformat()
        count = 0
        for row in rows:
            pid = row["pid"]
            started_at_str = row["started_at"]

            # Case 1: PID 已记录且进程仍存活 -> 跳过
            if pid and _is_pid_alive(int(pid)):
                continue

            # Case 2: PID 尚未记录 (子进程还没启动) -> 给予宽限期
            if not pid and started_at_str:
                try:
                    started_at = datetime.fromisoformat(started_at_str)
                    elapsed = (now - started_at).total_seconds()
                    if elapsed < 120:  # 2 分钟宽限期, 足够 ProcessPool 启动
                        continue
                except (ValueError, TypeError):
                    pass

            # Case 3: 进程确认已死亡 -> 标记失败
            conn.execute(
                "UPDATE tasks SET status = 'failed', finished_at = ?, "
                "error_message = '进程异常退出 (orphaned recovery)', "
                "progress_pct = 0, progress_message = '进程异常退出 (orphaned recovery)' "
                "WHERE task_id = ?",
                (now_str, row["task_id"]),
            )
            count += 1
        conn.commit()
        return count

    def update_progress(
        self,
        task_id: str,
        pct: int,
        message: str = "",
    ) -> None:
        """更新任务进度百分比和进度消息 (仅 running 状态有意义)。"""
        conn = self._get_conn()
        conn.execute(
            "UPDATE tasks SET progress_pct = ?, progress_message = ? WHERE task_id = ?",
            (min(max(pct, 0), 100), message, task_id),
        )
        conn.commit()

    def count_by_status(self, status: TaskStatus) -> int:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM tasks WHERE status = ?",
            (status.value,),
        ).fetchone()
        return row["cnt"] if row else 0
