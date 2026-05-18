"""
任务数据模型 -- 状态机 + 数据结构
"""
from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Optional


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @classmethod
    def allowed_transitions(cls) -> dict[TaskStatus, set[TaskStatus]]:
        return {
            cls.PENDING: {cls.RUNNING, cls.CANCELLED},
            cls.RUNNING: {cls.PAUSED, cls.SUCCEEDED, cls.FAILED, cls.CANCELLED},
            cls.PAUSED: {cls.RUNNING, cls.CANCELLED},
            cls.SUCCEEDED: set(),
            cls.FAILED: set(),
            cls.CANCELLED: set(),
        }

    def can_transition_to(self, target: TaskStatus) -> bool:
        return target in self.allowed_transitions().get(self, set())


@dataclass
class TaskRecord:
    task_id: str
    created_at: str                        # ISO 8601
    status: TaskStatus = TaskStatus.PENDING
    submit_source: str = "cli"             # "ui" | "cli"
    profile_path: Optional[str] = None
    config_snapshot_path: Optional[str] = None
    output_dir: Optional[str] = None
    model_name: str = ""
    universe_name: str = ""
    top_k: int = 0
    train_window: int = 0
    step: int = 0
    gap: int = 0
    steps: str = ""                          # 逗号分隔的执行步骤, e.g. "download,feature,backtest"
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error_message: Optional[str] = None
    retry_of_task_id: Optional[str] = None
    pid: Optional[int] = None
    progress_pct: int = 0
    progress_message: str = ""

    def to_dict(self) -> dict:
        d = {}
        for k in self.__dataclass_fields__:
            v = getattr(self, k)
            d[k] = v.value if isinstance(v, TaskStatus) else v
        return d

    @classmethod
    def from_dict(cls, d: dict) -> TaskRecord:
        d = dict(d)
        if "status" in d and isinstance(d["status"], str):
            d["status"] = TaskStatus(d["status"])
        valid = set(cls.__dataclass_fields__)
        d = {k: v for k, v in d.items() if k in valid}
        return cls(**d)
