"""
数据层依赖管理器 -- 分层依赖追踪与增量更新传播

职责：
  - 定义数据层之间的依赖关系
  - 计算每层上游数据指纹（不仅仅是配置）
  - 检测上游变化并判断下游是否需要更新
  - 支持增量传播：上游更新 -> 触发下游更新

数据层定义：
  Layer 0: stock_daily_cache/     -- 原始股票缓存（数据源产物）
  Layer 1: raw/zz500_10y_daily_clean.parquet + SQLite daily_bar -- 清洗后数据
  Layer 2: features/zz500_alpha158_raw.parquet -- 原始特征矩阵

依赖链：
  Layer 0 -> Layer 1 -> Layer 2

指纹机制：
  每层产物保存时，记录：
    - upstream_fingerprint: 上游数据的指纹（文件列表 + 总大小 + 最新修改时间）
    - config_fingerprint: 生成该层使用的配置参数指纹
    - created_at: 生成时间
    - row_count / file_size: 产物元数据
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


# ================================================================
# 数据结构
# ================================================================
@dataclass
class LayerFingerprint:
    """
    数据层指纹 -- 记录产物生成时的上游状态和配置。
    """
    layer_name: str                          # 层名称: cache / canonical / raw_feature
    output_path: str                         # 产物路径
    upstream_fingerprint: str                # 上游数据指纹
    config_fingerprint: str                  # 配置参数指纹
    created_at: str                          # 生成时间 (ISO 格式)
    row_count: int = 0                       # 行数
    file_size: int = 0                       # 文件大小 (bytes)
    n_stocks: int = 0                        # 股票数量
    n_features: int = 0                      # 因子数量 (仅 raw_feature 层)
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "layer_name": self.layer_name,
            "output_path": self.output_path,
            "upstream_fingerprint": self.upstream_fingerprint,
            "config_fingerprint": self.config_fingerprint,
            "created_at": self.created_at,
            "row_count": self.row_count,
            "file_size": self.file_size,
            "n_stocks": self.n_stocks,
            "n_features": self.n_features,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, d: dict) -> LayerFingerprint:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class LayerStatus:
    """
    数据层状态 -- 判断是否需要更新。
    """
    layer_name: str
    output_exists: bool
    fingerprint_exists: bool
    upstream_changed: bool
    config_changed: bool
    needs_update: bool
    reason: str


# ================================================================
# 指纹计算
# ================================================================
def compute_cache_fingerprint(cache_dir: str) -> str:
    """
    计算 Layer 0 (stock_daily_cache) 的指纹。
    基于目录内所有 parquet 文件的：文件列表 + 总大小 + 最新修改时间。
    """
    if not os.path.isdir(cache_dir):
        return ""

    files = sorted([
        f for f in os.listdir(cache_dir)
        if f.endswith(".parquet") and not f.startswith("_")
    ])

    if not files:
        return ""

    total_size = 0
    max_mtime = 0.0
    for f in files:
        fp = os.path.join(cache_dir, f)
        try:
            total_size += os.path.getsize(fp)
            max_mtime = max(max_mtime, os.path.getmtime(fp))
        except OSError:
            continue

    # 指纹 = 文件数 + 总大小 + 最新修改时间
    raw = f"{len(files)}|{total_size}|{max_mtime:.0f}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def compute_canonical_fingerprint(cfg: dict) -> str:
    """
    计算 Layer 1 (canonical) 的指纹。
    基于 SQLite daily_bar 表的行数 + 股票数 + 日期范围。
    """
    try:
        from src.data_layer.db import get_connection

        con = get_connection(cfg)
        row = con.execute("""
            SELECT COUNT(*), COUNT(DISTINCT code), MIN(date), MAX(date)
            FROM daily_bar
        """).fetchone()

        if not row or row[0] == 0:
            return ""

        count, n_codes, min_date, max_date = row
        raw = f"{count}|{n_codes}|{min_date}|{max_date}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
    except Exception as exc:
        logger.warning("compute_canonical_fingerprint 失败: %s", exc)
        return ""


def compute_config_fingerprint(cfg: dict, sections: list[str]) -> str:
    """
    计算配置参数指纹。
    与 storage_manager.config_hash 语义一致，但独立实现避免循环依赖。
    """
    subset = {k: cfg[k] for k in sections if k in cfg}
    raw = json.dumps(subset, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ================================================================
# 指纹存储
# ================================================================
def _get_fingerprint_dir() -> str:
    """指纹文件存储目录"""
    try:
        from src.paths import project_paths
        return project_paths.fingerprint_dir
    except Exception:
        return "data/cache/fingerprints"


def _layer_fp_path(layer_name: str) -> str:
    """层指纹文件路径"""
    fp_dir = _get_fingerprint_dir()
    return os.path.join(fp_dir, f"layer_{layer_name}.json")


def save_layer_fingerprint(fp: LayerFingerprint) -> None:
    """保存层指纹到文件"""
    fp_dir = _get_fingerprint_dir()
    os.makedirs(fp_dir, exist_ok=True)

    path = _layer_fp_path(fp.layer_name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(fp.to_dict(), f, indent=2, ensure_ascii=False)

    logger.info(
        "[LayerFingerprint] 保存 %s: upstream=%s, config=%s",
        fp.layer_name, fp.upstream_fingerprint[:8], fp.config_fingerprint[:8],
    )


def load_layer_fingerprint(layer_name: str) -> Optional[LayerFingerprint]:
    """加载层指纹"""
    path = _layer_fp_path(layer_name)
    if not os.path.exists(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            return LayerFingerprint.from_dict(json.load(f))
    except Exception as exc:
        logger.warning("加载层指纹失败 (%s): %s", layer_name, exc)
        return None


# ================================================================
# 数据层管理器
# ================================================================
class DataLayerManager:
    """
    数据层依赖管理器。

    用法：
        mgr = DataLayerManager(cfg)

        # 检查各层状态
        status = mgr.check_layer("canonical")
        if status.needs_update:
            print(f"需要更新: {status.reason}")

        # 检查所有层
        all_status = mgr.check_all_layers()

        # 保存指纹（在产物生成后调用）
        mgr.save_canonical_fingerprint(row_count=1000000, n_stocks=500)
    """

    LAYER_CACHE = "cache"           # Layer 0: 原始股票缓存
    LAYER_CANONICAL = "canonical"   # Layer 1: 清洗后数据
    LAYER_RAW_FEATURE = "raw_feature"  # Layer 2: 原始特征矩阵

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.etl = cfg.get("etl", {})
        self.features = cfg.get("features", {})

    # --------------------------------------------------
    # 层输出路径
    # --------------------------------------------------
    def get_cache_dir(self) -> str:
        """Layer 0: 原始股票缓存目录"""
        return self.etl.get("cache_dir", "data/stock_daily_cache")

    def get_canonical_path(self) -> str:
        """Layer 1: 清洗后数据路径"""
        return self.etl.get("raw_output", "data/raw/zz500_10y_daily_clean.parquet")

    def get_raw_feature_path(self) -> str:
        """Layer 2: 原始特征矩阵路径"""
        return self.features.get("raw_feature_output", "data/features/zz500_alpha158_raw.parquet")

    # --------------------------------------------------
    # 上游指纹计算
    # --------------------------------------------------
    def get_cache_fingerprint(self) -> str:
        """获取 Layer 0 当前状态的指纹"""
        return compute_cache_fingerprint(self.get_cache_dir())

    def get_canonical_fingerprint(self) -> str:
        """获取 Layer 1 当前状态的指纹"""
        return compute_canonical_fingerprint(self.cfg)

    def get_raw_feature_upstream_fingerprint(self) -> str:
        """
        获取 Layer 2 上游指纹。
        Layer 2 的上游是 Layer 1 (canonical)，所以使用 canonical 的指纹。
        """
        return self.get_canonical_fingerprint()

    # --------------------------------------------------
    # 配置指纹
    # --------------------------------------------------
    def get_etl_config_fingerprint(self) -> str:
        """ETL 配置指纹"""
        return compute_config_fingerprint(self.cfg, ["etl"])

    def get_feature_config_fingerprint(self) -> str:
        """特征配置指纹"""
        return compute_config_fingerprint(self.cfg, ["features", "engine", "price"])

    # --------------------------------------------------
    # 状态检查
    # --------------------------------------------------
    def check_layer(self, layer_name: str) -> LayerStatus:
        """
        检查指定层是否需要更新。

        Returns:
            LayerStatus: 包含是否需要更新及原因
        """
        if layer_name == self.LAYER_CANONICAL:
            return self._check_canonical()
        elif layer_name == self.LAYER_RAW_FEATURE:
            return self._check_raw_feature()
        else:
            raise ValueError(f"未知层: {layer_name}")

    def _check_canonical(self) -> LayerStatus:
        """检查 Layer 1 (canonical) 是否需要更新"""
        output_path = self.get_canonical_path()
        output_exists = os.path.exists(output_path)

        # 检查 SQLite daily_bar 表
        db_has_data = False
        try:
            from src.data_layer.db import table_row_count
            db_has_data = table_row_count(self.cfg, "daily_bar") > 0
        except Exception:
            pass

        # Layer 1 的输出包括 Parquet 和 SQLite
        effective_exists = output_exists and db_has_data

        # 加载已有指纹
        saved_fp = load_layer_fingerprint(self.LAYER_CANONICAL)
        fingerprint_exists = saved_fp is not None

        # 计算当前上游指纹 (Layer 0)
        current_upstream = self.get_cache_fingerprint()

        # 计算当前配置指纹
        current_config = self.get_etl_config_fingerprint()

        # 判断是否变化
        upstream_changed = False
        config_changed = False
        reason = ""

        if not effective_exists:
            reason = "产物不存在"
        elif not fingerprint_exists or saved_fp is None:
            reason = "无指纹记录"
        else:
            if saved_fp.upstream_fingerprint != current_upstream:
                upstream_changed = True
                reason = f"上游数据已变化 (旧={saved_fp.upstream_fingerprint[:8]}, 新={current_upstream[:8]})"
            elif saved_fp.config_fingerprint != current_config:
                config_changed = True
                reason = f"配置已变化 (旧={saved_fp.config_fingerprint[:8]}, 新={current_config[:8]})"

        needs_update = not effective_exists or not fingerprint_exists or upstream_changed or config_changed

        if not needs_update and saved_fp is not None:
            reason = f"有效 (生成于 {saved_fp.created_at[:19]})"

        return LayerStatus(
            layer_name=self.LAYER_CANONICAL,
            output_exists=effective_exists,
            fingerprint_exists=fingerprint_exists,
            upstream_changed=upstream_changed,
            config_changed=config_changed,
            needs_update=needs_update,
            reason=reason,
        )

    def _check_raw_feature(self) -> LayerStatus:
        """检查 Layer 2 (raw_feature) 是否需要更新"""
        output_path = self.get_raw_feature_path()
        output_exists = os.path.exists(output_path)

        # 加载已有指纹
        saved_fp = load_layer_fingerprint(self.LAYER_RAW_FEATURE)
        fingerprint_exists = saved_fp is not None

        # 计算当前上游指纹 (Layer 1 = canonical)
        current_upstream = self.get_raw_feature_upstream_fingerprint()

        # 计算当前配置指纹
        current_config = self.get_feature_config_fingerprint()

        # 判断是否变化
        upstream_changed = False
        config_changed = False
        reason = ""

        if not output_exists:
            reason = "产物不存在"
        elif not fingerprint_exists or saved_fp is None:
            reason = "无指纹记录"
        else:
            if saved_fp.upstream_fingerprint != current_upstream:
                upstream_changed = True
                reason = f"上游数据已变化 (canonical: {saved_fp.upstream_fingerprint[:8]} -> {current_upstream[:8]})"
            elif saved_fp.config_fingerprint != current_config:
                config_changed = True
                reason = f"配置已变化 (旧={saved_fp.config_fingerprint[:8]}, 新={current_config[:8]})"

        needs_update = not output_exists or not fingerprint_exists or upstream_changed or config_changed

        if not needs_update and saved_fp is not None:
            reason = f"有效 (生成于 {saved_fp.created_at[:19]})"

        return LayerStatus(
            layer_name=self.LAYER_RAW_FEATURE,
            output_exists=output_exists,
            fingerprint_exists=fingerprint_exists,
            upstream_changed=upstream_changed,
            config_changed=config_changed,
            needs_update=needs_update,
            reason=reason,
        )

    def check_all_layers(self) -> dict[str, LayerStatus]:
        """检查所有数据层状态"""
        return {
            self.LAYER_CANONICAL: self._check_canonical(),
            self.LAYER_RAW_FEATURE: self._check_raw_feature(),
        }

    # --------------------------------------------------
    # 指纹保存
    # --------------------------------------------------
    def save_canonical_fingerprint(
        self,
        row_count: int,
        n_stocks: int,
        file_size: int = 0,
    ) -> LayerFingerprint:
        """
        在 Layer 1 产物生成后保存指纹。

        Args:
            row_count: 总行数
            n_stocks: 股票数量
            file_size: Parquet 文件大小 (可选, 自动计算)
        """
        output_path = self.get_canonical_path()

        if file_size == 0 and os.path.exists(output_path):
            file_size = os.path.getsize(output_path)

        fp = LayerFingerprint(
            layer_name=self.LAYER_CANONICAL,
            output_path=output_path,
            upstream_fingerprint=self.get_cache_fingerprint(),
            config_fingerprint=self.get_etl_config_fingerprint(),
            created_at=datetime.now().isoformat(),
            row_count=row_count,
            file_size=file_size,
            n_stocks=n_stocks,
        )

        save_layer_fingerprint(fp)
        return fp

    def save_raw_feature_fingerprint(
        self,
        row_count: int,
        n_stocks: int,
        n_features: int,
        file_size: int = 0,
    ) -> LayerFingerprint:
        """
        在 Layer 2 产物生成后保存指纹。

        Args:
            row_count: 总行数
            n_stocks: 股票数量
            n_features: 因子数量
            file_size: Parquet 文件大小 (可选, 自动计算)
        """
        output_path = self.get_raw_feature_path()

        if file_size == 0 and os.path.exists(output_path):
            file_size = os.path.getsize(output_path)

        fp = LayerFingerprint(
            layer_name=self.LAYER_RAW_FEATURE,
            output_path=output_path,
            upstream_fingerprint=self.get_raw_feature_upstream_fingerprint(),
            config_fingerprint=self.get_feature_config_fingerprint(),
            created_at=datetime.now().isoformat(),
            row_count=row_count,
            file_size=file_size,
            n_stocks=n_stocks,
            n_features=n_features,
        )

        save_layer_fingerprint(fp)
        return fp

    # --------------------------------------------------
    # 报告
    # --------------------------------------------------
    def print_status_report(self) -> None:
        """打印所有数据层状态报告"""
        print("\n" + "=" * 60)
        print("数据层状态报告")
        print("=" * 60)

        # Layer 0: Cache
        cache_dir = self.get_cache_dir()
        cache_fp = self.get_cache_fingerprint()
        n_cache_files = 0
        if os.path.isdir(cache_dir):
            n_cache_files = len([
                f for f in os.listdir(cache_dir)
                if f.endswith(".parquet") and not f.startswith("_")
            ])
        print(f"\nLayer 0 [cache]:")
        print(f"  目录: {cache_dir}")
        print(f"  文件数: {n_cache_files}")
        print(f"  指纹: {cache_fp}")

        # Layer 1: Canonical
        canonical_status = self._check_canonical()
        print(f"\nLayer 1 [canonical]:")
        print(f"  输出: {self.get_canonical_path()}")
        print(f"  存在: {canonical_status.output_exists}")
        print(f"  需更新: {canonical_status.needs_update}")
        print(f"  原因: {canonical_status.reason}")

        # Layer 2: Raw Feature
        raw_feature_status = self._check_raw_feature()
        print(f"\nLayer 2 [raw_feature]:")
        print(f"  输出: {self.get_raw_feature_path()}")
        print(f"  存在: {raw_feature_status.output_exists}")
        print(f"  需更新: {raw_feature_status.needs_update}")
        print(f"  原因: {raw_feature_status.reason}")

        print("\n" + "=" * 60)


# ================================================================
# 便捷函数
# ================================================================
def check_data_layers(cfg: dict) -> dict[str, LayerStatus]:
    """
    检查所有数据层状态的便捷函数。

    用法:
        from src.data_layer.layer_manager import check_data_layers
        status = check_data_layers(cfg)
        if status["canonical"].needs_update:
            print("需要更新 canonical 层")
    """
    mgr = DataLayerManager(cfg)
    return mgr.check_all_layers()


def print_data_layer_report(cfg: dict) -> None:
    """打印数据层状态报告的便捷函数"""
    mgr = DataLayerManager(cfg)
    mgr.print_status_report()
