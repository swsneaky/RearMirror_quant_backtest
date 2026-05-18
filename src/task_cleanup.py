"""
实验任务保留期清理工具 -- experiments/tasks/task_* 的生命周期管理

授权范围:
  仅允许操作 experiments/tasks/task_* 目录

显式排除 (绝不触碰):
  - data/quant.db, quant.db-wal, quant.db-shm
  - data/features/ (含 .alpha158_ckpt/)
  - data/results/, data/raw/
  - experiments/.fingerprints/
  - models/, tools/, configs/, docs/
  - AI_CONTEXT.md, HANDOFF.md, WORKLOG.md
  - 根目录兼容 shim 与根目录历史脚本

授权来源: HANDOFF.md approved_cleanup_execution 切片
蓝图参考: docs/storage_management_blueprint.md Lane 1
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path


# ── 数据结构 ────────────────────────────────────────


@dataclass
class TaskCandidate:
    """一个 task 目录的清理候选信息"""
    path: str
    name: str
    size_bytes: int
    mtime_ts: float         # epoch
    mtime_human: str
    file_count: int
    reason: str             # "empty" | "expired" | "retained"
    protected: bool         # True = 不会被删除
    protection_reason: str  # "keep_last_n" | "pinned" | "within_retention" | ""

    @property
    def size_gb(self) -> float:
        return self.size_bytes / (1024 ** 3)


@dataclass
class CleanupManifest:
    """一次清理运行的完整留痕"""
    timestamp: str
    dry_run: bool
    retention_days: int
    keep_last_n: int
    pinned: list[str]
    max_delete_gb: float
    candidates: list[dict]
    deleted: list[dict]
    total_scanned: int
    total_delete_eligible: int
    total_deleted: int
    deleted_bytes: int
    fuse_triggered: bool


# ── 核心逻辑 ────────────────────────────────────────


def _dir_stats(dirpath: str) -> tuple[int, int, float]:
    """返回 (total_bytes, file_count, latest_mtime)"""
    total = 0
    count = 0
    latest_mtime = 0.0
    for root, _, files in os.walk(dirpath):
        for f in files:
            fp = os.path.join(root, f)
            try:
                st = os.stat(fp)
                total += st.st_size
                count += 1
                if st.st_mtime > latest_mtime:
                    latest_mtime = st.st_mtime
            except OSError:
                pass
    # 空目录: 用目录本身的 mtime
    if count == 0:
        try:
            latest_mtime = os.stat(dirpath).st_mtime
        except OSError:
            latest_mtime = 0.0
    return total, count, latest_mtime


def _parse_task_timestamp(name: str) -> datetime | None:
    """从 task_YYYYMMDD_HHMMSS_hex 中解析时间戳"""
    m = re.match(r"task_(\d{8})_(\d{6})_", name)
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)}_{m.group(2)}", "%Y%m%d_%H%M%S")
    except ValueError:
        return None


def enumerate_task_candidates(
    project_root: str | None = None,
    retention_days: int = 7,
    keep_last_n: int = 2,
    pinned: list[str] | None = None,
) -> list[TaskCandidate]:
    """
    枚举 experiments/tasks/task_* 目录, 标注每个目录的清理候选状态。

    Args:
        project_root: 项目根目录
        retention_days: 保留天数, 超过则标记为 expired
        keep_last_n: 无条件保留最新的 N 个 task 目录
        pinned: 被 pin 保护的 task 目录名列表

    Returns:
        TaskCandidate 列表 (已排序: 最新在前)
    """
    if project_root is None:
        from src.paths import project_paths
        project_root = project_paths.root

    if pinned is None:
        pinned = []

    tasks_root = os.path.join(project_root, "experiments", "tasks")

    # ── 安全校验: tasks_root 必须在项目内 ──
    resolved_root = Path(project_root).resolve()
    resolved_tasks = Path(tasks_root).resolve()
    if not resolved_tasks.is_relative_to(resolved_root):
        raise RuntimeError(
            f"[SAFETY] tasks_root 不在项目根目录内: {tasks_root}"
        )

    if not os.path.isdir(tasks_root):
        return []

    # 收集所有 task_* 目录
    task_dirs: list[tuple[str, str]] = []
    for entry in os.listdir(tasks_root):
        full = os.path.join(tasks_root, entry)
        if entry.startswith("task_") and os.path.isdir(full):
            task_dirs.append((entry, full))

    # 按名称排序 (时间戳在名称中, 所以字典序 = 时间序)
    task_dirs.sort(key=lambda x: x[0], reverse=True)

    cutoff = time.time() - timedelta(days=retention_days).total_seconds()
    pinned_set = set(pinned)

    candidates: list[TaskCandidate] = []
    for idx, (name, full_path) in enumerate(task_dirs):
        size_bytes, file_count, mtime = _dir_stats(full_path)
        mtime_human = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M") if mtime > 0 else "unknown"

        # 判断保护状态
        protected = False
        protection_reason = ""

        if name in pinned_set:
            protected = True
            protection_reason = "pinned"
        elif idx < keep_last_n:
            protected = True
            protection_reason = "keep_last_n"
        elif mtime >= cutoff:
            protected = True
            protection_reason = "within_retention"

        # 判断删除原因
        if protected:
            reason = "retained"
        elif file_count == 0:
            reason = "empty"
        else:
            reason = "expired"

        # ── 安全校验: 候选路径必须在 tasks_root 内 ──
        resolved_candidate = Path(full_path).resolve()
        if not resolved_candidate.is_relative_to(resolved_tasks):
            raise RuntimeError(
                f"[SAFETY] 候选路径越权: {full_path} 不在 experiments/tasks/ 内"
            )

        candidates.append(TaskCandidate(
            path=full_path,
            name=name,
            size_bytes=size_bytes,
            mtime_ts=mtime,
            mtime_human=mtime_human,
            file_count=file_count,
            reason=reason,
            protected=protected,
            protection_reason=protection_reason,
        ))

    return candidates


def execute_cleanup(
    candidates: list[TaskCandidate] | None = None,
    apply: bool = False,
    max_delete_gb: float = 7.0,
    manifest_dir: str | None = None,
    **enumerate_kwargs,
) -> CleanupManifest:
    """
    执行任务目录清理 (默认 dry-run)。

    Args:
        candidates: 预先枚举的候选列表; 为 None 则自动枚举
        apply: True 则执行真实删除; False 则仅 dry-run
        max_delete_gb: 单次运行最大删除量 (GB), 超过则停止
        manifest_dir: manifest 文件输出目录

    Returns:
        CleanupManifest 记录本次运行详情
    """
    if candidates is None:
        candidates = enumerate_task_candidates(**enumerate_kwargs)

    delete_eligible = [c for c in candidates if not c.protected]
    deleted: list[TaskCandidate] = []
    deleted_bytes = 0
    fuse_triggered = False
    max_delete_bytes = max_delete_gb * (1024 ** 3)

    for c in delete_eligible:
        # 保险丝对首个候选同样生效: 单个目录超过阈值则跳过, 不允许首删豁免
        if deleted_bytes + c.size_bytes > max_delete_bytes:
            fuse_triggered = True
            break

        if apply:
            try:
                shutil.rmtree(c.path)
                deleted.append(c)
                deleted_bytes += c.size_bytes
            except OSError as e:
                print(f"[ERROR] 删除失败: {c.path}: {e}")
        else:
            deleted.append(c)
            deleted_bytes += c.size_bytes

    # 构建 manifest
    now = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 从 enumerate_kwargs 提取策略参数
    retention_days = enumerate_kwargs.get("retention_days", 7)
    keep_last_n = enumerate_kwargs.get("keep_last_n", 2)
    pinned = enumerate_kwargs.get("pinned", [])

    manifest = CleanupManifest(
        timestamp=now,
        dry_run=not apply,
        retention_days=retention_days,
        keep_last_n=keep_last_n,
        pinned=pinned,
        max_delete_gb=max_delete_gb,
        candidates=[asdict(c) for c in candidates],
        deleted=[asdict(c) for c in deleted],
        total_scanned=len(candidates),
        total_delete_eligible=len(delete_eligible),
        total_deleted=len(deleted),
        deleted_bytes=deleted_bytes,
        fuse_triggered=fuse_triggered,
    )

    # 写 manifest 文件
    if manifest_dir is None:
        from src.paths import project_paths
        manifest_dir = os.path.join(project_paths.root, "logs")
    os.makedirs(manifest_dir, exist_ok=True)
    mode_tag = "apply" if apply else "dryrun"
    manifest_path = os.path.join(manifest_dir, f"cleanup_manifest_{now}_{mode_tag}.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(asdict(manifest), f, ensure_ascii=False, indent=2)

    return manifest


def print_cleanup_report(manifest: CleanupManifest) -> None:
    """打印清理报告"""
    mode = "DRY-RUN" if manifest.dry_run else "APPLY"

    print("=" * 60)
    print(f"[{mode}] 实验任务清理报告")
    print("=" * 60)
    print()
    print("授权范围: experiments/tasks/task_*")
    print("显式排除: data/features/ data/results/ data/raw/ data/quant.db")
    print("          experiments/.fingerprints/ models/ tools/ configs/ docs/")
    print()
    print(f"策略: retention_days={manifest.retention_days}, "
          f"keep_last_n={manifest.keep_last_n}, "
          f"max_delete_gb={manifest.max_delete_gb:.1f}")
    if manifest.pinned:
        print(f"Pinned: {', '.join(manifest.pinned)}")
    print()

    # 按状态分组
    retained = [c for c in manifest.candidates if c.get("protected")]
    eligible = [c for c in manifest.candidates if not c.get("protected")]

    if retained:
        print(f"保留 ({len(retained)} 个):")
        for c in retained:
            sz = c["size_bytes"] / (1024 ** 3)
            print(f"  ✓ {c['name']}  {sz:.2f} GB  {c['file_count']} files  "
                  f"reason={c['protection_reason']}")
        print()

    if eligible:
        action = "已删除" if not manifest.dry_run else "将删除"
        print(f"{action} ({len(manifest.deleted)} 个):")
        for c in manifest.deleted:
            sz = c["size_bytes"] / (1024 ** 3)
            print(f"  ✗ {c['name']}  {sz:.2f} GB  {c['file_count']} files  "
                  f"reason={c['reason']}")
        print()

    total_gb = manifest.deleted_bytes / (1024 ** 3)
    print(f"扫描: {manifest.total_scanned} 个任务目录")
    print(f"可删除: {manifest.total_delete_eligible} 个")
    print(f"{'已释放' if not manifest.dry_run else '预计释放'}: {total_gb:.2f} GB")
    if manifest.fuse_triggered:
        print(f"[FUSE] 已触发 max_delete_gb={manifest.max_delete_gb:.1f} 保险丝, "
              f"部分候选未处理")
    print("=" * 60)


# ── CLI 入口 ────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="实验任务保留期清理工具 (experiments/tasks/task_*)",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="执行真实删除; 不指定则为 dry-run",
    )
    parser.add_argument(
        "--retention-days", type=int, default=7,
        help="保留天数 (默认 7)",
    )
    parser.add_argument(
        "--keep-last-n", type=int, default=2,
        help="无条件保留最新 N 个任务目录 (默认 2)",
    )
    parser.add_argument(
        "--pinned", nargs="*", default=[],
        help="被 pin 保护的 task 目录名",
    )
    parser.add_argument(
        "--max-delete-gb", type=float, default=7.0,
        help="单次最大删除量 GB (默认 7.0)",
    )
    args = parser.parse_args()

    candidates = enumerate_task_candidates(
        retention_days=args.retention_days,
        keep_last_n=args.keep_last_n,
        pinned=args.pinned,
    )
    manifest = execute_cleanup(
        candidates=candidates,
        apply=args.apply,
        max_delete_gb=args.max_delete_gb,
        retention_days=args.retention_days,
        keep_last_n=args.keep_last_n,
        pinned=args.pinned,
    )
    print_cleanup_report(manifest)


if __name__ == "__main__":
    main()
