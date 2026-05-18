"""
dry-run 清理枚举工具 -- 只枚举可清理对象, 不执行真实删除

白名单范围 (仅允许枚举):
  1. QA 临时产物  -- qa/ 下所有文件
  2. 缓存         -- data/cache/ 下可重建文件
  3. 过期日志     -- logs/ 下超过 retention_days 的文件

禁止触碰 (黑名单, 不扫描也不枚举):
  - 正式资产 (data/raw/, data/features/, data/results/, data/quant.db)
  - 实验历史 (experiments/)
  - 正式模型 (models/)
  - 控制文件 (AI_CONTEXT.md, HANDOFF.md, WORKLOG.md)
  - 正式入口脚本 (pipeline.py, run_experiment.py, task_cli.py)
  - 根目录兼容 shim (_qa_neutralize_run.py, _formal_neutralize_run.py)
  - 根目录历史脚本 (test_duckdb.py, test_full_pipeline.py)
  - 工具脚本目录 (tools/)
  - 配置与文档 (configs/, docs/, README.md, pyproject.toml)

授权来源: HANDOFF.md cleanup_authorization_and_dryrun 切片
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


@dataclass
class CleanupCandidate:
    path: str
    category: str           # "qa" | "cache" | "log"
    size_bytes: int
    mtime: str              # human-readable

    @property
    def size_human(self) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if abs(self.size_bytes) < 1024:
                return f"{self.size_bytes:.1f} {unit}"
            self.size_bytes /= 1024  # type: ignore[assignment]
        return f"{self.size_bytes:.1f} TB"


def _scan_dir(root: str, category: str) -> list[CleanupCandidate]:
    """递归扫描目录下所有文件"""
    results: list[CleanupCandidate] = []
    if not os.path.isdir(root):
        return results
    for dirpath, _, filenames in os.walk(root):
        for fname in filenames:
            fp = os.path.join(dirpath, fname)
            try:
                st = os.stat(fp)
                results.append(CleanupCandidate(
                    path=fp,
                    category=category,
                    size_bytes=st.st_size,
                    mtime=datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                ))
            except OSError:
                pass
    return results


def _scan_expired_logs(
    logs_dir: str,
    retention_days: int = 30,
) -> list[CleanupCandidate]:
    """扫描超过 retention_days 的日志文件"""
    results: list[CleanupCandidate] = []
    if not os.path.isdir(logs_dir):
        return results
    cutoff = time.time() - timedelta(days=retention_days).total_seconds()
    for dirpath, _, filenames in os.walk(logs_dir):
        for fname in filenames:
            fp = os.path.join(dirpath, fname)
            try:
                st = os.stat(fp)
                if st.st_mtime < cutoff:
                    results.append(CleanupCandidate(
                        path=fp,
                        category="log",
                        size_bytes=st.st_size,
                        mtime=datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                    ))
            except OSError:
                pass
    return results


def enumerate_cleanable(
    project_root: str | None = None,
    log_retention_days: int = 30,
) -> list[CleanupCandidate]:
    """
    枚举所有可清理对象 (dry-run)。

    仅扫描白名单路径:
      - qa/                 -> QA 临时产物
      - data/cache/         -> 可重建缓存
      - logs/ (expired)     -> 过期日志

    Returns: CleanupCandidate 列表 (path, category, size, mtime)
    """
    if project_root is None:
        from src.paths import project_paths
        project_root = project_paths.root

    candidates: list[CleanupCandidate] = []

    # 1. QA 临时产物
    qa_root = os.path.join(project_root, "qa")
    candidates.extend(_scan_dir(qa_root, "qa"))

    # 2. 缓存 (data/cache/)
    cache_root = os.path.join(project_root, "data", "cache")
    candidates.extend(_scan_dir(cache_root, "cache"))

    # 3. 过期日志
    logs_root = os.path.join(project_root, "logs")
    candidates.extend(_scan_expired_logs(logs_root, log_retention_days))

    # ── 安全校验: 确保所有候选路径均在白名单目录内 ──
    # 使用 Path.is_relative_to 做真正的路径层级判断,
    # 防止 startswith 被 logs-evil / qa-evil 等相邻前缀绕过
    allowed_roots = [
        Path(p).resolve() for p in (qa_root, cache_root, logs_root)
    ]
    for c in candidates:
        resolved = Path(c.path).resolve()
        if not any(resolved.is_relative_to(ar) for ar in allowed_roots):
            raise RuntimeError(
                f"[SAFETY] 候选路径越权: {c.path} 不在白名单目录内"
            )

    return candidates


def print_dry_run_report(candidates: list[CleanupCandidate] | None = None) -> None:
    """打印 dry-run 枚举报告 (含可审计的白名单/黑名单边界摘要)"""
    if candidates is None:
        candidates = enumerate_cleanable()

    # ── 可审计边界摘要 ────────────────────────────
    print("=" * 60)
    print("[DRY-RUN] 清理授权边界摘要")
    print("=" * 60)
    print("白名单 (本次扫描范围):")
    print("  - qa/              QA 临时产物")
    print("  - data/cache/      可重建缓存")
    print("  - logs/ (expired)  超过 retention 的日志")
    print()
    print("黑名单 (绝对不触碰):")
    print("  - data/raw/  data/features/  data/results/  data/quant.db")
    print("  - experiments/  models/  tools/  configs/  docs/")
    print("  - AI_CONTEXT.md  HANDOFF.md  WORKLOG.md  README.md")
    print("  - pipeline.py  run_experiment.py  task_cli.py")
    print("  - _qa_neutralize_run.py  _formal_neutralize_run.py")
    print("  - test_duckdb.py  test_full_pipeline.py")
    print("=" * 60)
    print()

    if not candidates:
        print("[DRY-RUN] 无可清理对象")
        return

    total_bytes = sum(c.size_bytes for c in candidates)
    by_category: dict[str, list[CleanupCandidate]] = {}
    for c in candidates:
        by_category.setdefault(c.category, []).append(c)

    print(f"[DRY-RUN] 可清理对象: {len(candidates)} 个文件, "
          f"总计 {total_bytes / 1024 / 1024:.1f} MB")
    print()

    category_labels = {"qa": "QA 临时产物", "cache": "缓存", "log": "过期日志"}
    for cat in ("qa", "cache", "log"):
        items = by_category.get(cat, [])
        if not items:
            continue
        cat_bytes = sum(c.size_bytes for c in items)
        print(f"  [{category_labels[cat]}] {len(items)} 个文件, "
              f"{cat_bytes / 1024 / 1024:.1f} MB")
        for c in sorted(items, key=lambda x: x.path):
            print(f"    {c.path}  ({c.mtime})")
    print()
    print("[DRY-RUN] 以上为枚举结果, 未执行任何删除操作")


if __name__ == "__main__":
    print_dry_run_report()
