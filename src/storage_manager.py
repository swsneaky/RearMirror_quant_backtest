"""
存储管理器 -- 缓存 / 历史文件 / 空间监控 / 自动清理 / 缓存指纹
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ================================================================
# 数据结构
# ================================================================
@dataclass
class DirStats:
    """目录空间统计"""
    path: str
    total_bytes: int = 0
    file_count: int = 0
    oldest_mtime: Optional[float] = None
    newest_mtime: Optional[float] = None

    @property
    def total_human(self) -> str:
        return _human_size(self.total_bytes)

    @property
    def oldest_time(self) -> str:
        if self.oldest_mtime is None:
            return "-"
        return datetime.fromtimestamp(self.oldest_mtime).strftime("%Y-%m-%d %H:%M")

    @property
    def newest_time(self) -> str:
        if self.newest_mtime is None:
            return "-"
        return datetime.fromtimestamp(self.newest_mtime).strftime("%Y-%m-%d %H:%M")


@dataclass
class TaskDirInfo:
    """单个任务目录信息"""
    task_id: str
    path: str
    total_bytes: int = 0
    file_count: int = 0
    created: str = ""
    status: str = ""
    has_results: bool = False
    has_models: bool = False


@dataclass
class CacheFingerprint:
    """缓存指纹 -- 记录生成产物时使用的参数摘要"""
    output_path: str
    config_hash: str
    created_at: str
    file_size: int = 0
    row_count: int = 0
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "output_path": self.output_path,
            "config_hash": self.config_hash,
            "created_at": self.created_at,
            "file_size": self.file_size,
            "row_count": self.row_count,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, d: dict) -> CacheFingerprint:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ================================================================
# 工具函数
# ================================================================
def _human_size(nbytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


def config_hash(cfg: dict, sections: list[str] | None = None) -> str:
    """
    对 config 的指定 section 计算 SHA-256 摘要。
    参数变动时摘要会改变，用于判断缓存是否过期。
    """
    if sections:
        subset = {k: cfg[k] for k in sections if k in cfg}
    else:
        # 排除 _task / paths 等不影响产物内容的 section
        subset = {k: v for k, v in cfg.items() if k not in ("_task", "paths", "engine")}
    raw = json.dumps(subset, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ================================================================
# 空间扫描
# ================================================================
def scan_dir(path: str) -> DirStats:
    """递归统计目录大小、文件数、最旧/最新修改时间"""
    stats = DirStats(path=path)
    if not os.path.isdir(path):
        return stats
    for root, _dirs, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            try:
                sz = os.path.getsize(fp)
                mt = os.path.getmtime(fp)
            except OSError:
                continue
            stats.total_bytes += sz
            stats.file_count += 1
            if stats.oldest_mtime is None or mt < stats.oldest_mtime:
                stats.oldest_mtime = mt
            if stats.newest_mtime is None or mt > stats.newest_mtime:
                stats.newest_mtime = mt
    return stats


def scan_all_directories(cfg: dict) -> dict[str, DirStats]:
    """扫描项目中所有关键数据目录"""
    dirs = {
        "个股缓存 (stock_daily_cache)": cfg["etl"].get("cache_dir", "data/stock_daily_cache"),
        "原始数据 (data/raw)": cfg.get("paths", {}).get("data_raw", "data/raw"),
        "特征矩阵 (data/features)": cfg.get("paths", {}).get("data_features", "data/features"),
        "模型 (models/)": cfg.get("paths", {}).get("models", "models"),
        "日志 (logs/)": cfg.get("paths", {}).get("logs", "logs"),
        "任务产物 (experiments/)": "experiments",
    }
    return {name: scan_dir(p) for name, p in dirs.items()}


# ================================================================
# 任务产物管理
# ================================================================
def list_task_dirs(base: str = "experiments/tasks") -> list[TaskDirInfo]:
    """列出所有任务目录及其空间信息"""
    results = []
    if not os.path.isdir(base):
        return results
    for name in sorted(os.listdir(base), reverse=True):
        task_dir = os.path.join(base, name)
        if not os.path.isdir(task_dir):
            continue
        info = TaskDirInfo(task_id=name, path=task_dir)
        # 统计空间
        for root, _dirs, files in os.walk(task_dir):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    info.total_bytes += os.path.getsize(fp)
                    info.file_count += 1
                except OSError:
                    pass
        # 解析快照获取状态
        snapshot = os.path.join(task_dir, "config_snapshot.yaml")
        if os.path.exists(snapshot):
            try:
                import yaml
                with open(snapshot, "r", encoding="utf-8") as f:
                    snap_cfg = yaml.safe_load(f)
                task_meta = snap_cfg.get("_task", {})
                info.created = task_meta.get("task_id", name)
                info.status = task_meta.get("submit_source", "")
            except Exception as exc:
                logger.warning("任务 %s 配置快照解析失败: %s", name, exc)
        info.has_results = os.path.isdir(os.path.join(task_dir, "results"))
        info.has_models = os.path.isdir(os.path.join(task_dir, "models"))
        results.append(info)
    return results


def cleanup_task_dirs(
    task_ids: list[str],
    base: str = "experiments/tasks",
) -> list[str]:
    """删除指定任务目录，返回成功删除的 task_id 列表"""
    removed = []
    for tid in task_ids:
        task_dir = os.path.join(base, tid)
        if os.path.isdir(task_dir):
            shutil.rmtree(task_dir, ignore_errors=True)
            removed.append(tid)
    return removed


def find_cleanable_tasks(
    store,
    max_age_days: int = 30,
    statuses: tuple[str, ...] = ("failed", "cancelled"),
) -> list[str]:
    """
    找出可清理的任务：状态为 failed/cancelled 且超过 max_age_days 天。
    """
    from src.tasking.models import TaskStatus
    cutoff = (datetime.now() - timedelta(days=max_age_days)).isoformat()
    candidates = []
    for status_str in statuses:
        try:
            ts = TaskStatus(status_str)
        except ValueError:
            continue
        tasks = store.list_tasks(status=ts, limit=500)
        for t in tasks:
            if t.created_at and t.created_at < cutoff:
                candidates.append(t.task_id)
    return candidates


# ================================================================
# 缓存指纹 (Fingerprint)
# ================================================================
def _get_fingerprint_dir() -> str:
    try:
        from src.paths import project_paths
        return project_paths.fingerprint_dir
    except Exception:
        return "data/cache/fingerprints"

_FINGERPRINT_DIR = _get_fingerprint_dir()


def _fp_path(output_path: str) -> str:
    """根据产物路径生成指纹文件路径"""
    safe = output_path.replace("/", "_").replace("\\", "_").replace(":", "_")
    return os.path.join(_FINGERPRINT_DIR, f"{safe}.json")


def save_fingerprint(
    output_path: str,
    cfg: dict,
    sections: list[str],
    row_count: int = 0,
    extra: dict | None = None,
) -> CacheFingerprint:
    """在产物生成后保存指纹"""
    os.makedirs(_FINGERPRINT_DIR, exist_ok=True)
    fp = CacheFingerprint(
        output_path=output_path,
        config_hash=config_hash(cfg, sections),
        created_at=datetime.now().isoformat(),
        file_size=os.path.getsize(output_path) if os.path.exists(output_path) else 0,
        row_count=row_count,
        extra=extra or {},
    )
    with open(_fp_path(output_path), "w", encoding="utf-8") as f:
        json.dump(fp.to_dict(), f, indent=2, ensure_ascii=False)
    return fp


def load_fingerprint(output_path: str) -> CacheFingerprint | None:
    """加载已有指纹"""
    p = _fp_path(output_path)
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        return CacheFingerprint.from_dict(json.load(f))


def check_cache_fresh(output_path: str, cfg: dict, sections: list[str]) -> tuple[bool, str]:
    """
    检查缓存是否新鲜。
    返回 (is_fresh, reason)。
    """
    if not os.path.exists(output_path):
        return False, "文件不存在"

    fp = load_fingerprint(output_path)
    if fp is None:
        return False, "无指纹记录 (可能是旧版生成)"

    current_hash = config_hash(cfg, sections)
    if fp.config_hash != current_hash:
        return False, f"参数已变更 (旧={fp.config_hash}, 新={current_hash})"

    # 检查文件大小是否匹配 (防篡改或不完整写入)
    actual_size = os.path.getsize(output_path)
    if fp.file_size > 0 and abs(actual_size - fp.file_size) > 1024:
        return False, f"文件大小不匹配 (期望={_human_size(fp.file_size)}, 实际={_human_size(actual_size)})"

    return True, f"有效 (生成于 {fp.created_at[:19]}, {_human_size(actual_size)})"


def list_all_fingerprints() -> list[CacheFingerprint]:
    """列出所有指纹"""
    results = []
    if not os.path.isdir(_FINGERPRINT_DIR):
        return results
    for fname in os.listdir(_FINGERPRINT_DIR):
        if fname.endswith(".json"):
            fp_path = os.path.join(_FINGERPRINT_DIR, fname)
            try:
                with open(fp_path, "r", encoding="utf-8") as f:
                    results.append(CacheFingerprint.from_dict(json.load(f)))
            except Exception as exc:
                logger.warning("指纹文件解析失败 (%s): %s", fname, exc)
    return results


def clear_stale_fingerprints() -> int:
    """清理指向不存在文件的指纹"""
    if not os.path.isdir(_FINGERPRINT_DIR):
        return 0
    removed = 0
    for fname in os.listdir(_FINGERPRINT_DIR):
        if not fname.endswith(".json"):
            continue
        fp_path = os.path.join(_FINGERPRINT_DIR, fname)
        try:
            with open(fp_path, "r", encoding="utf-8") as f:
                fp = CacheFingerprint.from_dict(json.load(f))
            if not os.path.exists(fp.output_path):
                os.remove(fp_path)
                removed += 1
        except Exception as exc:
            logger.warning("指纹清理失败 (%s): %s", fname, exc)
    return removed
