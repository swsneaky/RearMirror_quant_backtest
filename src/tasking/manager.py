"""
任务管理器 -- 创建 / 取消 / 重试 / 查询
base_config.yaml 始终只读，所有参数通过内存合并 -> 快照落盘
"""
from __future__ import annotations

import copy
import os
import uuid
from datetime import datetime
from typing import Optional

import yaml

from src.config_loader import load_config, load_experiment_config
from src.tasking.models import TaskRecord, TaskStatus
from src.tasking.store import TaskStore


def _generate_task_id() -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    short = uuid.uuid4().hex[:6]
    return f"task_{ts}_{short}"


def _deep_merge(base: dict, overlay: dict) -> dict:
    merged = copy.deepcopy(base)
    for key, val in overlay.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
            merged[key] = _deep_merge(merged[key], val)
        else:
            merged[key] = copy.deepcopy(val)
    return merged


def _extract_overrides(cfg: dict) -> dict:
    overrides = {}
    for key in ("model", "backtest", "label", "features"):
        if key in cfg:
            overrides[key] = copy.deepcopy(cfg[key])
    return overrides


class TaskManager:
    """统一任务 CRUD，CLI 和 UI 共用"""

    def __init__(self, store: Optional[TaskStore] = None):
        self.store = store or TaskStore()

    def submit(
        self,
        *,
        profile_path: Optional[str] = None,
        ui_overrides: Optional[dict] = None,
        submit_source: str = "cli",
        steps: Optional[list[str]] = None,
        notes: str = "",
    ) -> TaskRecord:
        """
        创建一个新任务:
          1. 合并 base_config + profile + ui_overrides -> 最终 cfg
          2. 生成 task_id 和独立输出目录
          3. 将 cfg 快照为 config_snapshot.yaml（不可变）
          4. 写入 SQLite
        """
        if steps is None:
            steps = ["raw_feature", "neutralize", "backtest"]

        task_id = _generate_task_id()
        output_dir = os.path.join("experiments", "tasks", task_id)
        os.makedirs(output_dir, exist_ok=True)

        # 1. 合并配置
        if profile_path:
            cfg = load_experiment_config(profile_path, exp_dir=output_dir)
        else:
            cfg = copy.deepcopy(load_config())
            cfg["features"]["output"] = os.path.join(
                output_dir, "features", "alpha158.parquet"
            )
            cfg["paths"]["models"] = os.path.join(output_dir, "models")
            cfg["paths"]["logs"] = os.path.join(output_dir, "logs")
            cfg["paths"]["data_features"] = os.path.join(output_dir, "features")

        # 2. 应用 UI 覆盖
        if ui_overrides:
            cfg = _deep_merge(cfg, ui_overrides)

        # 3. 注入任务元信息
        cfg.setdefault("_task", {})
        cfg["_task"]["task_id"] = task_id
        cfg["_task"]["steps"] = steps
        cfg["_task"]["notes"] = notes
        cfg["_task"]["submit_source"] = submit_source

        # 4. 快照落盘
        snapshot_path = os.path.join(output_dir, "config_snapshot.yaml")
        with open(snapshot_path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        # 5. 构建记录
        bt = cfg.get("backtest", {})
        record = TaskRecord(
            task_id=task_id,
            created_at=datetime.now().isoformat(),
            status=TaskStatus.PENDING,
            submit_source=submit_source,
            profile_path=profile_path or "",
            config_snapshot_path=snapshot_path,
            output_dir=output_dir,
            model_name=cfg.get("model", {}).get("active", ""),
            universe_name=cfg.get("etl", {}).get("index_name", ""),
            top_k=bt.get("top_k", 0),
            train_window=bt.get("train_window", 0),
            step=bt.get("test_step", 0),
            gap=bt.get("gap", 0),
            steps=",".join(steps),
        )
        self.store.insert(record)
        return record

    def cancel(self, task_id: str) -> bool:
        task = self.store.get(task_id)
        if task is None:
            raise ValueError(f"任务 {task_id} 不存在")
        if not task.status.can_transition_to(TaskStatus.CANCELLED):
            raise ValueError(
                f"任务 {task_id} 当前状态 {task.status.value}，无法取消"
            )
        if task.output_dir:
            cancel_flag = os.path.join(task.output_dir, ".cancel")
            os.makedirs(os.path.dirname(cancel_flag) or ".", exist_ok=True)
            with open(cancel_flag, "w") as f:
                f.write(datetime.now().isoformat())
        return self.store.update_status(
            task_id, TaskStatus.CANCELLED,
            finished_at=datetime.now().isoformat(),
        )

    def retry(self, task_id: str, submit_source: str = "cli") -> TaskRecord:
        old = self.store.get(task_id)
        if old is None:
            raise ValueError(f"任务 {task_id} 不存在")
        if old.status != TaskStatus.FAILED:
            raise ValueError(f"只能重试 failed 任务，当前: {old.status.value}")

        with open(old.config_snapshot_path, "r", encoding="utf-8") as f:
            old_cfg = yaml.safe_load(f)

        steps = old_cfg.get("_task", {}).get("steps", ["raw_feature", "neutralize", "backtest"])
        new_task = self.submit(
            ui_overrides=_extract_overrides(old_cfg),
            submit_source=submit_source,
            steps=steps,
            profile_path=old.profile_path or None,
        )
        # 标记重试关系
        conn = self.store._get_conn()
        conn.execute(
            "UPDATE tasks SET retry_of_task_id = ? WHERE task_id = ?",
            (task_id, new_task.task_id),
        )
        conn.commit()
        return new_task

    def get(self, task_id: str) -> Optional[TaskRecord]:
        return self.store.get(task_id)

    def list_tasks(self, status: Optional[TaskStatus] = None, limit: int = 100):
        return self.store.list_tasks(status=status, limit=limit)
