"""
统一日志工具 -- 所有模块通过 get_logger(__name__) 获取 logger

默认行为:
  - 控制台输出 INFO 级别，带时间戳和模块名
  - 子进程 (tasking runner) 可通过 logging.basicConfig(force=True) 覆盖 handler
  - 静默失败点统一用 logger.warning() 替代 print / pass
"""
import logging
import sys

_CONFIGURED = False


def _ensure_root_handler():
    """首次调用时为 root logger 添加一个 stderr handler (幂等)"""
    global _CONFIGURED
    if _CONFIGURED:
        return
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        root.addHandler(handler)
    if root.level == logging.WARNING:
        root.setLevel(logging.INFO)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """获取模块级 logger，首次调用时自动配置 root handler"""
    _ensure_root_handler()
    return logging.getLogger(name)
