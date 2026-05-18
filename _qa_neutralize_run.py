"""
[DEPRECATED SHIM] 此文件已迁移到 tools/qa_neutralize_run.py
正式入口: python tools/qa_neutralize_run.py
本 shim 仅为兼容过渡保留，不得作为新增脚本默认位置。
"""
import warnings

warnings.warn(
    "_qa_neutralize_run.py 已迁移到 tools/qa_neutralize_run.py，请使用新路径。",
    DeprecationWarning,
    stacklevel=2,
)

# 重导出 collect_stats 以兼容 _formal_neutralize_run.py 的 import
from tools.qa_neutralize_run import collect_stats, main  # noqa: F401

if __name__ == "__main__":
    raise SystemExit(main())
