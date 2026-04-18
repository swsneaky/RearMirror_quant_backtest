"""
Label Store -- 标签矩阵的存储和读取

职责：
  - 接收 label_gen.generate_labels() 的产出，只保留 label_ 列 + 主键列
  - 与 FeatureStore 平行，由 DatasetBuilder 负责拼装
  - 支持后续扩展多种标签定义（不同 horizon、不同 method）

存储后端：
  - 正式入口: 版本化标签表 label__{hash} (通过 label_set_id 访问)
  - 兼容别名: label_wide 表 (过渡产物，后续应迁移到版本化表)
  - 导出副本: Parquet 文件 (仅用于导入导出 / 灵活分享)
"""
from __future__ import annotations

import logging
import os

import pandas as pd

logger = logging.getLogger(__name__)


class LabelStore:
    """
    标签矩阵存储 -- 只存 label_ 列 + 主键。

    用法：
        store = LabelStore.from_config(cfg)
        store.save(df, label_name)
        df = store.load()
    """

    KEY_COLS = ["date", "code"]
    # label_wide 是兼容别名表，不是长期正式入口。
    # 正式下游应优先通过 label_set_id 访问版本化表 label__{hash}。
    TABLE_NAME = "label_wide"

    def __init__(self, store_path: str, cfg: dict | None = None):
        self.store_path = store_path
        self.cfg = cfg or {}

    @classmethod
    def from_config(cls, cfg: dict) -> LabelStore:
        feat_dir = cfg.get("paths", {}).get("data_features", "data/features")
        return cls(
            store_path=os.path.join(feat_dir, "label_store.parquet"),
            cfg=cfg,
        )

    # --------------------------------------------------
    # SQLite 检测
    # --------------------------------------------------
    def _use_db(self) -> bool:
        if not self.cfg:
            return False
        try:
            from src.data_layer.db import table_exists
            return table_exists(self.cfg, self.TABLE_NAME)
        except Exception as exc:
            logger.warning("LabelStore SQLite 检测失败，回退 Parquet: %s", exc)
            return False

    # --------------------------------------------------
    # 写入
    # --------------------------------------------------
    def save(self, df: pd.DataFrame, label_name: str, label_config: dict | None = None) -> tuple[str, str | None]:
        """
        保存标签矩阵到 SQLite + Parquet。

        v2 新增:
        - label_config: 用于计算 asset_id 的标签配置字典

        如果提供 label_config, 会:
          1. 写入版本化表 label__{hash}
          2. 注册到 asset_registry
          3. 同时更新 label_wide 别名 (兼容)

        Returns: (Parquet 落盘路径, asset_id 或 None)
        """
        label_cols = [c for c in df.columns if c.startswith("label_")]
        if label_name not in label_cols:
            label_cols.append(label_name)
        keep = self.KEY_COLS + label_cols
        keep = [c for c in keep if c in df.columns]
        out = df[keep].sort_values(self.KEY_COLS).reset_index(drop=True)

        # SQLite 写入 (主存储)
        returned_asset_id = None

        # SQLite 写入 (主存储)
        if self.cfg:
            from src.data_layer.db import (
                ingest_dataframe, record_version, register_asset,
            )

            # v2: 版本化表
            if label_config:
                try:
                    from src.data_layer.asset_id import make_asset_id, make_table_name, make_config_hash
                    asset_id = make_asset_id("label_set", label_config)
                    versioned_table = make_table_name("label_set", label_config)
                    config_hash = make_config_hash(label_config)

                    ingest_dataframe(self.cfg, versioned_table, out, mode="replace")
                    print(f"[TAG] LabelStore -> SQLite [{versioned_table}]  "
                          f"({out.shape[0]} 行 x {len(label_cols)} 标签)")

                    register_asset(
                        self.cfg,
                        asset_id=asset_id,
                        asset_type="label_set",
                        name=label_name,
                        config_hash=config_hash,
                        table_name=versioned_table,
                        row_count=len(out),
                        col_count=len(label_cols),
                        meta={"label_cols": label_cols},
                    )

                    # 注册成功后才设置返回值
                    returned_asset_id = asset_id
                except Exception as e:
                    logger.warning("LabelStore 版本化表写入失败: %s", e)

            # 兼容别名 (独立 try，不受版本化表失败影响)
            try:
                ingest_dataframe(self.cfg, self.TABLE_NAME, out, mode="replace")
                record_version(
                    self.cfg, self.TABLE_NAME,
                    version=pd.Timestamp.now().strftime("%Y%m%d_%H%M%S"),
                    row_count=len(out), col_count=len(label_cols),
                )
                if not label_config:
                    print(f"[TAG] LabelStore -> SQLite [{self.TABLE_NAME}]  "
                          f"({out.shape[0]} 行 x {len(label_cols)} 标签)")
            except Exception as e:
                logger.warning("LabelStore 兼容别名写入失败: %s", e)

        # Parquet 写入 (兼容)
        os.makedirs(os.path.dirname(self.store_path) or ".", exist_ok=True)
        out.to_parquet(self.store_path, index=False, engine="pyarrow")
        print(f"[TAG] LabelStore -> Parquet: {self.store_path}  "
              f"({out.shape[0]} 行 x {len(label_cols)} 标签)")
        return self.store_path, returned_asset_id

    # --------------------------------------------------
    # 读取
    # --------------------------------------------------
    def load(
        self,
        label_name: str | None = None,
        date_range: tuple[str, str] | None = None,
    ) -> pd.DataFrame:
        """加载标签矩阵：优先 SQLite，回退 Parquet"""
        if self._use_db():
            return self._load_from_db(label_name, date_range)
        return self._load_from_parquet(label_name, date_range)

    def _load_from_db(
        self,
        label_name: str | None = None,
        date_range: tuple[str, str] | None = None,
    ) -> pd.DataFrame:
        from src.data_layer.db import get_connection
        con = get_connection(self.cfg)

        if label_name:
            cols = ", ".join(f'"{c}"' for c in self.KEY_COLS + [label_name])
        else:
            cols = "*"

        conditions = []
        params = []
        if date_range:
            conditions.append("date >= ? AND date <= ?")
            params.extend([date_range[0], date_range[1]])

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT {cols} FROM {self.TABLE_NAME} {where} ORDER BY code, date"
        df = con.execute(sql, params).df()
        df["date"] = pd.to_datetime(df["date"])
        return df

    def _load_from_parquet(
        self,
        label_name: str | None = None,
        date_range: tuple[str, str] | None = None,
    ) -> pd.DataFrame:
        if not os.path.exists(self.store_path):
            raise FileNotFoundError(f"LabelStore 文件不存在: {self.store_path}")

        df = pd.read_parquet(self.store_path)
        df["date"] = pd.to_datetime(df["date"])

        if date_range:
            df = df[(df["date"] >= date_range[0]) & (df["date"] <= date_range[1])]
        if label_name:
            keep = self.KEY_COLS + [label_name]
            df = df[[c for c in keep if c in df.columns]]

        return df

    def list_labels(self) -> list[str]:
        """列出当前存储的所有标签名"""
        if self._use_db():
            from src.data_layer.db import list_table_columns
            cols = list_table_columns(self.cfg, self.TABLE_NAME)
            return [c for c in cols if c.startswith("label_")]

        if not os.path.exists(self.store_path):
            return []
        import pyarrow.parquet as pq
        schema = pq.read_schema(self.store_path)
        return [n for n in schema.names if n.startswith("label_")]

    @property
    def exists(self) -> bool:
        if self._use_db():
            return True
        return os.path.exists(self.store_path)
