"""
Canonical Data Store -- 规范化数据层的只读封装

职责：
  - 提供规范化的市场数据视图：日线、行业、可交易状态
  - 是 FeatureStore / LabelStore / DatasetBuilder 的上游唯一数据源
  - 不负责下载，只负责读取和验证已有的 canonical 数据

严格模式 (require_db=True, 默认):
  - 研究主流程必须依赖 canonical DB (daily_bar)
  - DB 不可用时直接报错，不允许静默回退 Parquet

宽松模式 (require_db=False):
  - 仅用于导出工具、灾难恢复、离线调试
  - 数据源优先级：SQLite daily_bar 表 -> Parquet 文件 (fallback)
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class CanonicalStore:
    """
    规范化数据层 -- canonical 市场数据的只读封装。

    用法：
        # 研究主流程 (默认严格模式，DB 不可用即报错)
        store = CanonicalStore.from_config(cfg)

        # 导出/恢复/调试工具 (宽松模式，允许 Parquet fallback)
        store = CanonicalStore.from_config(cfg, require_db=False)

        daily = store.load_daily()            # date, code, raw_*, cum_factor
        industry = store.load_industry()      # code, industry
        flags = store.load_tradeability()     # date, code, isST, tradestatus
    """
    raw_path: str
    industry_path: str
    cfg: dict = field(default_factory=dict, repr=False)
    require_db: bool = field(default=True, repr=True)
    _cache: dict | None = field(default=None, repr=False)

    # --------------------------------------------------
    # 工厂方法
    # --------------------------------------------------
    @classmethod
    def from_config(cls, cfg: dict, require_db: bool = True) -> CanonicalStore:
        return cls(
            raw_path=cfg["etl"]["raw_output"],
            industry_path=cfg["etl"]["industry_map"],
            cfg=cfg,
            require_db=require_db,
        )

    # --------------------------------------------------
    # SQLite 检测
    # --------------------------------------------------
    def _use_db(self) -> bool:
        """判断是否使用 SQLite 后端"""
        if not self.cfg:
            return False
        try:
            from src.data_layer.db import table_row_count
            return table_row_count(self.cfg, "daily_bar") > 0
        except Exception as exc:
            if self.require_db:
                raise RuntimeError(
                    f"CanonicalStore 严格模式: daily_bar 不可用 ({exc})。"
                    "研究主流程必须依赖 canonical DB。"
                    "如需 Parquet fallback，请使用 require_db=False。"
                ) from exc
            logger.warning("CanonicalStore SQLite 检测失败，回退 Parquet: %s", exc)
            return False

    # --------------------------------------------------
    # 加载接口
    # --------------------------------------------------
    def _load_raw(self) -> pd.DataFrame:
        """
        加载并缓存全量数据。

        严格模式 (require_db=True): 必须从 SQLite daily_bar 加载，不可用即报错。
        宽松模式 (require_db=False): 优先 SQLite，回退 Parquet。
        """
        if self._cache is None:
            db_available = self._use_db()
            if db_available:
                df = self._load_from_db()
            elif self.require_db:
                raise RuntimeError(
                    "CanonicalStore 严格模式: daily_bar 为空或不存在。"
                    "请先运行 ETL (merge_and_clean) 将数据入库到 canonical 层。"
                    "如需 Parquet fallback，请使用 require_db=False。"
                )
            else:
                logger.warning(
                    "CanonicalStore: daily_bar 不可用，回退 Parquet (%s)。"
                    "仅限导出/恢复/离线调试场景。", self.raw_path,
                )
                df = self._load_from_parquet()
            self._cache = {"raw": df}
        return self._cache["raw"]

    def _load_from_db(self) -> pd.DataFrame:
        """从 SQLite daily_bar 加载"""
        from src.data_layer.db import get_connection
        con = get_connection(self.cfg)
        df = con.execute("SELECT * FROM daily_bar ORDER BY code, date").df()
        df["date"] = pd.to_datetime(df["date"])
        df["code"] = df["code"].astype(str)
        return df

    def _load_from_parquet(self) -> pd.DataFrame:
        """从 Parquet 文件加载 (仅限 require_db=False 的导出/恢复/调试场景)"""
        if not os.path.exists(self.raw_path):
            raise FileNotFoundError(f"Canonical 数据文件不存在: {self.raw_path}")
        df = pd.read_parquet(self.raw_path)
        df["date"] = pd.to_datetime(df["date"])
        df["code"] = df["code"].astype(str)
        return df

    def load_daily(self) -> pd.DataFrame:
        """
        返回日线全量数据。
        列：date, code, raw_open, raw_high, raw_low, raw_close,
            raw_volume, raw_amount, raw_pctChg, cum_factor, ...
        """
        return self._load_raw().copy()

    def load_industry(self) -> pd.DataFrame:
        """
        返回行业映射表。
        列：code, industry
        """
        if self._use_db():
            from src.data_layer.db import get_connection, table_row_count
            if table_row_count(self.cfg, "industry_map") > 0:
                con = get_connection(self.cfg)
                return con.execute("SELECT * FROM industry_map").df()
        if not os.path.exists(self.industry_path):
            raise FileNotFoundError(f"行业映射文件不存在: {self.industry_path}")
        return pd.read_parquet(self.industry_path)

    def load_tradeability(self) -> pd.DataFrame:
        """
        返回可交易状态子集。
        列：date, code, isST, tradestatus, raw_pctChg (用于涨跌停判断)
        """
        if self._use_db():
            from src.data_layer.db import get_connection
            con = get_connection(self.cfg)
            df = con.execute("""
                SELECT date, code, isST, tradestatus, raw_pctChg
                FROM daily_bar
                ORDER BY code, date
            """).df()
            df["date"] = pd.to_datetime(df["date"])
            df["code"] = df["code"].astype(str)
            return df

        df = self._load_raw()
        cols = ["date", "code"]
        for c in ["isST", "tradestatus", "raw_pctChg"]:
            if c in df.columns:
                cols.append(c)
        return df[cols].copy()

    def validate(self) -> list[str]:
        """验证 canonical 数据完整性，返回问题列表"""
        issues = []
        if self._use_db():
            from src.data_layer.db import list_table_columns
            cols = list_table_columns(self.cfg, "daily_bar")
            for c in ["date", "code", "raw_close"]:
                if c not in cols:
                    issues.append(f"daily_bar 缺少必要列: {c}")
        else:
            if not os.path.exists(self.raw_path):
                issues.append(f"raw 文件不存在: {self.raw_path}")
            if not os.path.exists(self.industry_path):
                issues.append(f"行业映射文件不存在: {self.industry_path}")
            if not issues:
                df = self._load_raw()
                required = ["date", "code", "raw_close"]
                missing = [c for c in required if c not in df.columns]
                if missing:
                    issues.append(f"缺少必要列: {missing}")
        return issues
