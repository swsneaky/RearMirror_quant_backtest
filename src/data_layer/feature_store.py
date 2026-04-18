"""
Feature Store -- 因子矩阵的存储和读取

职责：
  - 接收 feature_engine + cross_section 的产出，只保留 feat_ 列 + 元数据列
  - 提供按 universe / 日期范围 / 因子子集的读取接口
  - 与 LabelStore 平行，由 DatasetBuilder 负责拼装

存储后端：
  - 正式入口: 版本化特征表 feat__{hash} (通过 feature_set_id 访问)
  - 兼容别名: feature_wide 表 (过渡产物，后续应迁移到版本化表)
  - 导出副本: Parquet 文件 (仅用于导入导出 / 灵活分享)
"""
from __future__ import annotations

import logging
import os
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


class FeatureStore:
    """
    因子矩阵存储 -- 只存 feat_ 列 + 元数据键。

    用法：
        store = FeatureStore.from_config(cfg)
        store.save(df, features)
        df = store.load()
        df = store.load(feature_subset=["feat_ROC5", "feat_MA10"])
    """

    META_COLS = ["date", "code", "industry"]
    # feature_wide 是兼容别名表，不是长期正式入口。
    # 正式下游应优先通过 feature_set_id 访问版本化表 feat__{hash}。
    TABLE_NAME = "feature_wide"

    def __init__(self, store_path: str, cfg: dict | None = None):
        self.store_path = store_path
        self.cfg = cfg or {}

    @classmethod
    def from_config(cls, cfg: dict) -> FeatureStore:
        feat_dir = cfg.get("paths", {}).get("data_features", "data/features")
        return cls(
            store_path=os.path.join(feat_dir, "feature_store.parquet"),
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
            logger.warning("FeatureStore SQLite 检测失败，回退 Parquet: %s", exc)
            return False

    # --------------------------------------------------
    # 增量状态与 upsert
    # --------------------------------------------------
    def get_feature_state(self) -> dict[str, Any] | None:
        """
        返回 SQLite feature_wide 当前状态。

        raw_feature 的 DB-first 增量路径只使用 SQLite 状态作为事实源；
        Parquet snapshot 缺失或落后不影响这里的判断。
        """
        if not self._use_db():
            return None

        from src.data_layer.db import get_connection, list_table_columns, table_row_count

        row_count = table_row_count(self.cfg, self.TABLE_NAME)
        if row_count <= 0:
            return None

        con = get_connection(self.cfg)
        row = con.execute(
            f"SELECT MIN(date), MAX(date), COUNT(DISTINCT code) FROM {self.TABLE_NAME}"
        ).fetchone()
        if row is None or row[1] is None:
            return None

        cols = list_table_columns(self.cfg, self.TABLE_NAME)
        features = [c for c in cols if c.startswith("feat_")]
        if not features:
            return None

        return {
            "min_date": pd.to_datetime(row[0]),
            "max_date": pd.to_datetime(row[1]),
            "row_count": int(row_count),
            "code_count": int(row[2] or 0),
            "features": features,
            "columns": cols,
        }

    def upsert_raw_features(
        self,
        df: pd.DataFrame,
        features: list[str],
        *,
        extra_cols: list[str] | None = None,
        snapshot_path: str | None = None,
        export_snapshot: bool = True,
    ) -> dict[str, Any]:
        """
        将 raw feature 增量写入 SQLite feature_wide，并可选刷新 Parquet snapshot。

        该方法用于 raw_feature 的 DB-first staging/cache 子层：SQLite 写入是
        正式闭环，Parquet 仅是可重建的 snapshot/export，失败不应阻断 DB 成功。
        """
        from src.data_layer.db import (
            get_connection,
            list_table_columns,
            record_version,
            table_exists,
            table_row_count,
        )

        extra_cols = extra_cols or []
        keep = [c for c in self.META_COLS if c in df.columns]
        keep += [c for c in extra_cols if c in df.columns and c not in keep]
        keep += [c for c in features if c in df.columns and c not in keep]
        if "date" not in keep or "code" not in keep:
            raise ValueError("raw feature upsert 需要 date/code 主键列。")

        out = df[keep].copy()
        out["date"] = pd.to_datetime(out["date"]).dt.strftime("%Y-%m-%d %H:%M:%S")
        out["code"] = out["code"].astype(str)
        out = out.sort_values(["code", "date"]).reset_index(drop=True)

        con = get_connection(self.cfg)
        before_rows = table_row_count(self.cfg, self.TABLE_NAME)

        if not table_exists(self.cfg, self.TABLE_NAME):
            con.df_to_table(self.TABLE_NAME, out, if_exists="replace", chunksize=50_000)
        else:
            existing_cols = list_table_columns(self.cfg, self.TABLE_NAME)
            for col in out.columns:
                if col not in existing_cols:
                    sql_type = "TEXT" if col in {"date", "code", "industry"} else "REAL"
                    con.execute(f'ALTER TABLE {self.TABLE_NAME} ADD COLUMN "{col}" {sql_type}')
                    existing_cols.append(col)

            aligned = out.reindex(columns=existing_cols)
            tmp = f"_tmp_{self.TABLE_NAME}_upsert"
            con.df_to_table(tmp, aligned, if_exists="replace", chunksize=50_000)
            cols_sql = ", ".join(f'"{c}"' for c in existing_cols)
            con.execute(f"""
                DELETE FROM {self.TABLE_NAME}
                WHERE (date, code) IN (SELECT date, code FROM {tmp})
            """)
            con.execute(f"""
                INSERT INTO {self.TABLE_NAME} ({cols_sql})
                SELECT {cols_sql} FROM {tmp}
            """)
            con.execute(f"DROP TABLE IF EXISTS {tmp}")

        after_rows = table_row_count(self.cfg, self.TABLE_NAME)
        record_version(
            self.cfg,
            self.TABLE_NAME,
            version=pd.Timestamp.now().strftime("%Y%m%d_%H%M%S"),
            row_count=after_rows,
            col_count=len(features),
            extra="raw_feature_db_first_upsert",
        )

        snapshot_written = False
        snapshot_error: str | None = None
        snapshot_path = snapshot_path or self.store_path
        if export_snapshot:
            try:
                os.makedirs(os.path.dirname(snapshot_path) or ".", exist_ok=True)
                snap_df = self.load()
                snap_df.to_parquet(snapshot_path, index=False, engine="pyarrow")
                snapshot_written = True
                print(
                    f"[SNAPSHOT] raw feature Parquet snapshot: {snapshot_path} "
                    f"({len(snap_df):,} 行)",
                    flush=True,
                )
            except Exception as exc:
                snapshot_error = str(exc)
                logger.warning(
                    "raw feature Parquet snapshot 刷新失败 (DB upsert 已完成): %s",
                    exc,
                )

        print(
            f"[DB] raw feature upsert -> {self.TABLE_NAME}: "
            f"input={len(out):,}, rows {before_rows:,} -> {after_rows:,}, "
            f"features={len(features)}",
            flush=True,
        )
        return {
            "input_rows": len(out),
            "row_count_before": before_rows,
            "row_count_after": after_rows,
            "upserted_rows": len(out),
            "feature_count": len(features),
            "snapshot_path": snapshot_path,
            "snapshot_written": snapshot_written,
            "snapshot_error": snapshot_error,
        }

    # --------------------------------------------------
    # 写入
    # --------------------------------------------------
    def save(
        self,
        df: pd.DataFrame,
        features: list[str],
        feature_config: dict | None = None,
        factor_ids: list[str] | None = None,
    ) -> tuple[str, str | None]:
        """
        保存因子矩阵到 SQLite + Parquet。

        v2 新增:
        - feature_config: 用于计算 asset_id 的配置字典 (features + cross_section)
        - factor_ids: 组成此 feature_set 的因子定义 ID 列表

        如果提供 feature_config, 会:
          1. 写入版本化表 feat__{hash}
          2. 注册到 asset_registry
          3. 登记 feature_set_factors
          4. 同时更新 feature_wide 别名 (兼容)

        Returns: (Parquet 落盘路径, asset_id 或 None)
        """
        keep = [c for c in self.META_COLS if c in df.columns] + features
        out = df[keep].sort_values(["code", "date"]).reset_index(drop=True)

        # SQLite 写入 (主存储)
        returned_asset_id = None
        if self.cfg:
            from src.data_layer.db import (
                ingest_dataframe, record_version,
                register_asset, register_feature_set_factors,
            )

            # v2: 版本化表
            asset_id = None
            if feature_config:
                try:
                    from src.data_layer.asset_id import make_asset_id, make_table_name, make_config_hash
                    asset_id = make_asset_id("feature_set", feature_config)
                    versioned_table = make_table_name("feature_set", feature_config)
                    config_hash = make_config_hash(feature_config)

                    # 写入版本化表
                    ingest_dataframe(self.cfg, versioned_table, out, mode="replace")
                    print(f"[PKG] FeatureStore -> SQLite [{versioned_table}]  "
                          f"({out.shape[0]} 行 x {len(features)} 因子)")

                    # 注册到 asset_registry
                    register_asset(
                        self.cfg,
                        asset_id=asset_id,
                        asset_type="feature_set",
                        name=f"alpha158_{self.cfg.get('etl', {}).get('index_name', 'unknown')}",
                        config_hash=config_hash,
                        table_name=versioned_table,
                        row_count=len(out),
                        col_count=len(features),
                        meta={"features": features},
                    )

                    # 注册成功后才设置返回值
                    returned_asset_id = asset_id

                    # 登记因子组成
                    if factor_ids:
                        register_feature_set_factors(self.cfg, asset_id, factor_ids)
                except Exception as e:
                    logger.warning("FeatureStore 版本化表写入失败: %s", e)

            # 兼容别名 (独立 try，不受版本化表失败影响)
            try:
                ingest_dataframe(self.cfg, self.TABLE_NAME, out, mode="replace")
                record_version(
                    self.cfg, self.TABLE_NAME,
                    version=pd.Timestamp.now().strftime("%Y%m%d_%H%M%S"),
                    row_count=len(out), col_count=len(features),
                )
                if not asset_id:
                    print(f"[PKG] FeatureStore -> SQLite [{self.TABLE_NAME}]  "
                          f"({out.shape[0]} 行 x {len(features)} 因子)")
            except Exception as e:
                logger.warning("FeatureStore 兼容别名写入失败: %s", e)

        # Parquet 写入 (兼容)
        os.makedirs(os.path.dirname(self.store_path) or ".", exist_ok=True)
        out.to_parquet(self.store_path, index=False, engine="pyarrow")
        print(f"[PKG] FeatureStore -> Parquet: {self.store_path}  "
              f"({out.shape[0]} 行 x {len(features)} 因子)")
        return self.store_path, returned_asset_id

    # --------------------------------------------------
    # 读取
    # --------------------------------------------------
    def load(
        self,
        feature_subset: list[str] | None = None,
        date_range: tuple[str, str] | None = None,
        universe: list[str] | None = None,
    ) -> pd.DataFrame:
        """
        加载因子矩阵：优先 SQLite (支持谓词下推)，回退 Parquet。
        """
        if self._use_db():
            return self._load_from_db(feature_subset, date_range, universe)
        return self._load_from_parquet(feature_subset, date_range, universe)

    def _load_from_db(
        self,
        feature_subset: list[str] | None = None,
        date_range: tuple[str, str] | None = None,
        universe: list[str] | None = None,
    ) -> pd.DataFrame:
        """SQLite 读取 -- 利用 SQL 做列裁剪和行过滤"""
        from src.data_layer.db import get_connection
        con = get_connection(self.cfg)

        # 列选择
        if feature_subset:
            meta = [c for c in self.META_COLS]
            cols = ", ".join(f'"{c}"' for c in meta + feature_subset)
        else:
            cols = "*"

        # WHERE 条件
        conditions = []
        params = []
        if date_range:
            conditions.append("date >= ? AND date <= ?")
            params.extend([date_range[0], date_range[1]])
        if universe:
            placeholders = ", ".join(["?"] * len(universe))
            conditions.append(f"code IN ({placeholders})")
            params.extend(universe)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT {cols} FROM {self.TABLE_NAME} {where} ORDER BY code, date"
        df = con.execute(sql, params).df()
        df["date"] = pd.to_datetime(df["date"])
        return df

    def _load_from_parquet(
        self,
        feature_subset: list[str] | None = None,
        date_range: tuple[str, str] | None = None,
        universe: list[str] | None = None,
    ) -> pd.DataFrame:
        """Parquet 读取 (fallback)"""
        if not os.path.exists(self.store_path):
            raise FileNotFoundError(f"FeatureStore 文件不存在: {self.store_path}")

        df = pd.read_parquet(self.store_path)
        df["date"] = pd.to_datetime(df["date"])

        if date_range:
            df = df[(df["date"] >= date_range[0]) & (df["date"] <= date_range[1])]
        if universe:
            df = df[df["code"].isin(universe)]
        if feature_subset:
            keep = [c for c in self.META_COLS if c in df.columns] + feature_subset
            df = df[keep]

        return df

    def list_features(self) -> list[str]:
        """列出当前存储的所有因子名"""
        if self._use_db():
            from src.data_layer.db import list_table_columns
            cols = list_table_columns(self.cfg, self.TABLE_NAME)
            return [c for c in cols if c.startswith("feat_")]

        if not os.path.exists(self.store_path):
            return []
        import pyarrow.parquet as pq
        schema = pq.read_schema(self.store_path)
        return [n for n in schema.names if n.startswith("feat_")]

    @property
    def exists(self) -> bool:
        if self._use_db():
            return True
        return os.path.exists(self.store_path)
