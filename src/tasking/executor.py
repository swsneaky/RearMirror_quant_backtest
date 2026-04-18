"""
后台执行器 -- 轮询 pending 任务并分配给 worker 池
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ProcessPoolExecutor, Future
from typing import Optional

from src.tasking.models import TaskStatus
from src.tasking.store import TaskStore
from src.tasking.runner import run_task


class TaskExecutor:
    """
    后台调度器:
      - 启动一个守护线程轮询 SQLite 中的 pending 任务
      - 将任务分发给 ProcessPoolExecutor (max_workers)
      - 外层多任务并发，单任务内部 n_jobs=1 (由 config 保证)
    """

    def __init__(
        self,
        store: Optional[TaskStore] = None,
        max_workers: int = 2,
        poll_interval: float = 3.0,
    ):
        self.store = store or TaskStore()
        self.max_workers = max_workers
        self.poll_interval = poll_interval
        self._pool: Optional[ProcessPoolExecutor] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._futures: dict[str, Future] = {}

    def start(self):
        """启动执行器（幂等）"""
        if self._thread and self._thread.is_alive():
            return

        # 恢复异常退出的 orphaned 任务
        recovered = self.store.recover_orphaned()
        if recovered:
            print(f"[WARN]  已恢复 {recovered} 个 orphaned 任务为 failed")

        self._stop_event.clear()
        self._pool = ProcessPoolExecutor(max_workers=self.max_workers)
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        print(f"[RUN] TaskExecutor 已启动 (max_workers={self.max_workers})")

    def stop(self):
        """优雅关闭"""
        self._stop_event.set()
        if self._pool:
            self._pool.shutdown(wait=False)
        if self._thread:
            self._thread.join(timeout=10)

    @property
    def running_count(self) -> int:
        return self.store.count_by_status(TaskStatus.RUNNING)

    def _poll_loop(self):
        while not self._stop_event.is_set():
            try:
                self._dispatch_pending()
                self._cleanup_futures()
            except Exception as e:
                print(f"[WARN]  Executor 轮询异常: {e}")
            time.sleep(self.poll_interval)

    def _dispatch_pending(self):
        """如果有空闲 worker 槽位，从 pending 队列取任务"""
        active = sum(1 for f in self._futures.values() if not f.done())
        while active < self.max_workers:
            task = self.store.claim_pending()
            if task is None:
                break
            future = self._pool.submit(
                run_task,
                task.config_snapshot_path,
                task.output_dir,
                self.store._db_path,
                task.task_id,
            )
            self._futures[task.task_id] = future
            active += 1

    def _cleanup_futures(self):
        done = [tid for tid, f in self._futures.items() if f.done()]
        for tid in done:
            del self._futures[tid]
