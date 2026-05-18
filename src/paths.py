"""
统一路径解析器 -- 所有文件输出路径的唯一入口

目录分层:
  data/
    db/               <- 正式数据库 (SQLite WAL)
    raw/              <- 原始层 (canonical 入库前的规范化中间产物)
    cache/            <- 可重建缓存 (stock_daily_cache, checkpoint 等)
    features/         <- 正式特征/标签 versioned asset + compat parquet
    results/          <- 正式回测结果 + 因子分析
  experiments/        <- 实验产物 (按实验 ID 隔离)
  models/             <- 正式模型
  logs/               <- 正式运行日志
  qa/                 <- QA 临时产物 (sandbox DB, smoke parquet)
  tools/              <- 工具与草稿脚本

使用方法:
    from src.paths import project_paths
    db_path   = project_paths.formal_db
    qa_dir    = project_paths.qa_root
    qa_db     = project_paths.qa_db("neutralize_smoke")
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _find_project_root() -> Path:
    """从 __file__ 向上查找包含 configs/base_config.yaml 的目录"""
    here = Path(__file__).resolve().parent          # src/
    candidate = here.parent                          # RearMirror/
    if (candidate / "configs" / "base_config.yaml").is_file():
        return candidate
    # fallback: cwd
    cwd = Path.cwd()
    if (cwd / "configs" / "base_config.yaml").is_file():
        return cwd
    return candidate


@dataclass(frozen=True)
class ProjectPaths:
    """
    中央路径解析器。所有路径均为项目相对路径的 str 表示。

    规则:
      - 正式资产: data/ 下按类别子目录
      - 实验产物: experiments/{exp_id}/
      - QA 临时产物: qa/{session_name}/
      - 日志: logs/
      - 模型: models/
      - 工具脚本: tools/
    """
    root: str = field(default_factory=lambda: str(_find_project_root()))

    # ── 正式资产 ──────────────────────────────────
    @property
    def data_root(self) -> str:
        return os.path.join(self.root, "data")

    @property
    def formal_db(self) -> str:
        """正式 SQLite 数据库"""
        return os.path.join(self.data_root, "quant.db")

    @property
    def data_raw(self) -> str:
        return os.path.join(self.data_root, "raw")

    @property
    def data_features(self) -> str:
        return os.path.join(self.data_root, "features")

    @property
    def data_results(self) -> str:
        return os.path.join(self.data_root, "results")

    # ── 缓存 ─────────────────────────────────────
    @property
    def cache_root(self) -> str:
        return os.path.join(self.data_root, "cache")

    @property
    def stock_daily_cache(self) -> str:
        return os.path.join(self.cache_root, "stock_daily")

    @property
    def feature_checkpoint_dir(self) -> str:
        return os.path.join(self.cache_root, "alpha158_ckpt")

    @property
    def fingerprint_dir(self) -> str:
        return os.path.join(self.cache_root, "fingerprints")

    # ── 实验产物 ──────────────────────────────────
    @property
    def experiments_root(self) -> str:
        return os.path.join(self.root, "experiments")

    def experiment_dir(self, exp_id: str) -> str:
        return os.path.join(self.experiments_root, exp_id)

    # ── QA 临时产物 ───────────────────────────────
    @property
    def qa_root(self) -> str:
        return os.path.join(self.root, "qa")

    def qa_session_dir(self, session_name: str) -> str:
        return os.path.join(self.qa_root, session_name)

    def qa_db(self, session_name: str) -> str:
        return os.path.join(self.qa_session_dir(session_name), "quant_qa.db")

    # ── 日志 ──────────────────────────────────────
    @property
    def logs_root(self) -> str:
        return os.path.join(self.root, "logs")

    # ── 模型 ──────────────────────────────────────
    @property
    def models_root(self) -> str:
        return os.path.join(self.root, "models")

    # ── 工具/草稿脚本 ─────────────────────────────
    @property
    def tools_root(self) -> str:
        return os.path.join(self.root, "tools")

    # ── 便捷: 注入 cfg dict ──────────────────────
    def inject_into_config(self, cfg: dict) -> dict:
        """
        将统一路径注入到 cfg dict 中, 替换散落硬编码默认值。
        只覆盖 "paths" 部分, 不改业务参数。
        """
        paths = cfg.setdefault("paths", {})
        paths.setdefault("data_raw", self.data_raw)
        paths.setdefault("data_features", self.data_features)
        paths.setdefault("data_results", self.data_results)
        paths.setdefault("models", self.models_root)
        paths.setdefault("logs", self.logs_root)

        db = cfg.setdefault("database", {})
        db.setdefault("path", self.formal_db)

        etl = cfg.setdefault("etl", {})
        etl.setdefault("cache_dir", self.stock_daily_cache)

        return cfg

    def build_qa_paths(self, session_name: str) -> dict:
        """
        为 QA sandbox 生成隔离路径 dict, 供 _qa_neutralize_run.py 等使用。
        """
        qa_dir = self.qa_session_dir(session_name)
        return {
            "db_path": self.qa_db(session_name),
            "features_dir": os.path.join(qa_dir, "features"),
            "results_dir": os.path.join(qa_dir, "results"),
            "logs_dir": os.path.join(qa_dir, "logs"),
            "models_dir": os.path.join(qa_dir, "models"),
        }


# 全局单例
project_paths = ProjectPaths()
