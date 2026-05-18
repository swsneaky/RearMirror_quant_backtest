"""
Dataset Builder -- 按配置组装训练/分析用数据集

职责：
  - 从 FeatureStore + LabelStore + CanonicalStore 拼装完整数据集
  - 负责 join 逻辑、可交易性标记、回测辅助列注入
  - 是 backtest / ic_analysis 的唯一数据入口
  - 拼装前执行 feature/label 配对校验 (universe 一致性)
  - 同时提供"兼容性合并产物"用于过渡期 dashboard

SQLite 模式下使用 SQL JOIN 替代 pandas merge，减少内存拷贝。

Schema 协议：
  主键        : [date, code]
  元数据      : industry
  因子        : feat_*
  标签        : label_*
  可交易性    : isST, tradestatus
  回测辅助    : raw_pctChg, raw_amount
"""
from __future__ import annotations

import logging
import os

import pandas as pd

logger = logging.getLogger(__name__)

from src.data_layer.canonical import CanonicalStore
from src.data_layer.feature_store import FeatureStore
from src.data_layer.label_store import LabelStore
from src.runtime_modes import resolve_runtime_mode


class DatasetBuilder:
    """
    数据集组装器 -- 从三层数据资产拼装训练/分析用数据集。

    用法：
        builder = DatasetBuilder.from_config(cfg)
        train_df = builder.build_train_dataset()
        analysis_df = builder.build_analysis_dataset(features_only=True)
    """

    def __init__(
        self,
        canonical: CanonicalStore,
        feature_store: FeatureStore,
        label_store: LabelStore,
        cfg: dict | None = None,
    ):
        self.canonical = canonical
        self.feature_store = feature_store
        self.label_store = label_store
        self.cfg = cfg or {}

    @classmethod
    def from_config(cls, cfg: dict) -> DatasetBuilder:
        return cls(
            canonical=CanonicalStore.from_config(cfg),
            feature_store=FeatureStore.from_config(cfg),
            label_store=LabelStore.from_config(cfg),
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
            return (
                table_exists(self.cfg, "feature_wide")
                and table_exists(self.cfg, "label_wide")
            )
        except Exception as exc:
            logger.warning("DatasetBuilder SQLite 检测失败，回退 pandas merge: %s", exc)
            return False

    # --------------------------------------------------
    # Feature/Label 配对校验
    # --------------------------------------------------
    def validate_feature_label_pair(
        self,
        feature_set_id: str | None = None,
        label_set_id: str | None = None,
        *,
        date_range: tuple[str, str] | None = None,
        max_missing_ratio: float = 0.0,
        sample_report_limit: int = 20,
    ) -> dict:
        """
        校验 feature_set 与 label_set 的 universe 一致性。

        在训练集/分析集构建前调用，输出配对统计并在不合规时阻断。

        Args:
            feature_set_id: 版本化特征集 ID (None 则使用 feature_wide 兼容表)
            label_set_id:   版本化标签集 ID (None 则使用 label_wide 兼容表)
            max_missing_ratio: 最大允许的独有行比例 (0.0 = 严格模式)
            sample_report_limit: 差异样本报告最大条数

        Returns:
            包含 feature_rows, label_rows, intersection_rows,
            feature_only_rows, label_only_rows, feature_date_range,
            label_date_range 的统计字典

        Raises:
            ValueError: 当差异超出 max_missing_ratio 容忍范围时
        """
        feat_keys, label_keys = self._load_pair_keys(
            feature_set_id,
            label_set_id,
            date_range=date_range,
        )

        feat_set = set(map(tuple, feat_keys.values))
        label_set = set(map(tuple, label_keys.values))

        intersection = feat_set & label_set
        feat_only = feat_set - label_set
        label_only = label_set - feat_set

        feat_dates = feat_keys["date"]
        label_dates = label_keys["date"]

        report = {
            "feature_rows": len(feat_set),
            "label_rows": len(label_set),
            "intersection_rows": len(intersection),
            "feature_only_rows": len(feat_only),
            "label_only_rows": len(label_only),
            "feature_date_range": (str(feat_dates.min()), str(feat_dates.max())),
            "label_date_range": (str(label_dates.min()), str(label_dates.max())),
        }

        # 输出配对报告
        total = max(len(feat_set), len(label_set), 1)
        feat_only_ratio = len(feat_only) / total
        label_only_ratio = len(label_only) / total

        print(f"[PAIR] Feature/Label 配对校验:")
        print(f"  feature: {report['feature_rows']:,} 行  "
              f"({report['feature_date_range'][0]} ~ {report['feature_date_range'][1]})")
        print(f"  label:   {report['label_rows']:,} 行  "
              f"({report['label_date_range'][0]} ~ {report['label_date_range'][1]})")
        print(f"  交集:    {report['intersection_rows']:,} 行")
        if feat_only:
            print(f"  feature 独有: {len(feat_only):,} 行 ({feat_only_ratio:.1%})")
            if sample_report_limit > 0:
                samples = sorted(feat_only)[:sample_report_limit]
                for d, c in samples:
                    print(f"    {d} {c}")
        if label_only:
            print(f"  label 独有:   {len(label_only):,} 行 ({label_only_ratio:.1%})")
            if sample_report_limit > 0:
                samples = sorted(label_only)[:sample_report_limit]
                for d, c in samples:
                    print(f"    {d} {c}")

        # 阻断判定
        missing_ratio = max(feat_only_ratio, label_only_ratio)
        if missing_ratio > max_missing_ratio and (feat_only or label_only):
            raise ValueError(
                f"Feature/Label 配对校验未通过: "
                f"feature 独有 {len(feat_only)} 行 ({feat_only_ratio:.1%}), "
                f"label 独有 {len(label_only)} 行 ({label_only_ratio:.1%}), "
                f"超出容忍阈值 {max_missing_ratio:.1%}。"
                f"请检查 warmup/horizon/停牌/过滤规则是否能解释全部差异。"
            )

        return report

    def _load_pair_keys(
        self,
        feature_set_id: str | None,
        label_set_id: str | None,
        *,
        date_range: tuple[str, str] | None = None,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """加载 feature 和 label 的 (date, code) 主键用于配对校验"""
        if self._use_db():
            from src.data_layer.db import get_connection
            con = get_connection(self.cfg)
            feat_table, label_table = self._resolve_table_names(feature_set_id, label_set_id)
            params = []
            where = ""
            if date_range:
                where = " WHERE date >= ? AND date <= ?"
                params.extend([date_range[0], date_range[1]])
            feat_keys = con.execute(
                f"SELECT date, code FROM {feat_table}{where}",
                params,
            ).df()
            label_keys = con.execute(
                f"SELECT date, code FROM {label_table}{where}",
                params,
            ).df()
        else:
            feat_df = self.feature_store.load(date_range=date_range)
            label_df = self.label_store.load(date_range=date_range)
            feat_keys = feat_df[["date", "code"]].copy()
            label_keys = label_df[["date", "code"]].copy()
        feat_keys["date"] = pd.to_datetime(feat_keys["date"])
        label_keys["date"] = pd.to_datetime(label_keys["date"])
        return feat_keys, label_keys

    def _resolve_table_names(
        self,
        feature_set_id: str | None = None,
        label_set_id: str | None = None,
    ) -> tuple[str, str]:
        """
        解析实际的 SQLite 表名。

        如果指定了 feature_set_id / label_set_id，从 asset_registry 查找版本化表名；
        否则回退到 feature_wide / label_wide 兼容别名。
        """
        feat_table = "feature_wide"
        label_table = "label_wide"

        if feature_set_id or label_set_id:
            try:
                from src.data_layer.db import get_asset
                if feature_set_id:
                    asset = get_asset(self.cfg, feature_set_id)
                    if asset and asset.get("table_name"):
                        feat_table = asset["table_name"]
                if label_set_id:
                    asset = get_asset(self.cfg, label_set_id)
                    if asset and asset.get("table_name"):
                        label_table = asset["table_name"]
            except Exception as exc:
                logger.warning("版本化表名解析失败，回退兼容别名: %s", exc)

        return feat_table, label_table

    def _list_available_feature_columns(
        self,
        feature_set_id: str | None = None,
    ) -> list[str]:
        if self._use_db():
            from src.data_layer.db import list_table_columns

            feat_table, _ = self._resolve_table_names(feature_set_id, None)
            cols = list_table_columns(self.cfg, feat_table)
            return [c for c in cols if c.startswith("feat_")]
        return self.feature_store.list_features()

    def _list_available_label_columns(
        self,
        label_set_id: str | None = None,
    ) -> list[str]:
        if self._use_db():
            from src.data_layer.db import list_table_columns

            _, label_table = self._resolve_table_names(None, label_set_id)
            cols = list_table_columns(self.cfg, label_table)
            return [c for c in cols if c.startswith("label_")]
        return self.label_store.list_labels()

    def _resolve_recent_date_range(
        self,
        feature_set_id: str | None,
        recent_trade_dates: int | None,
    ) -> tuple[str, str] | None:
        if not recent_trade_dates or recent_trade_dates <= 0:
            return None

        if self._use_db():
            from src.data_layer.db import get_connection

            con = get_connection(self.cfg)
            feat_table, _ = self._resolve_table_names(feature_set_id, None)
            row = con.execute(
                f"""
                SELECT MIN(date), MAX(date)
                FROM (
                    SELECT DISTINCT date
                    FROM {feat_table}
                    ORDER BY date DESC
                    LIMIT ?
                )
                """,
                [int(recent_trade_dates)],
            ).fetchone()
            if row and row[0] and row[1]:
                return row[0], row[1]
            return None

        feat_df = self.feature_store.load()
        if feat_df.empty:
            return None
        unique_dates = feat_df["date"].drop_duplicates().sort_values().reset_index(drop=True)
        window = unique_dates.tail(int(recent_trade_dates))
        if window.empty:
            return None
        return str(window.iloc[0]), str(window.iloc[-1])

    def resolve_train_runtime_plan(
        self,
        feature_set_id: str | None = None,
        label_set_id: str | None = None,
        *,
        runtime_mode: str | None = None,
        feature_subset: list[str] | None = None,
        date_range: tuple[str, str] | None = None,
    ) -> dict:
        mode_name, mode_cfg = resolve_runtime_mode(self.cfg, runtime_mode)
        available_features = self._list_available_feature_columns(feature_set_id)

        resolved_feature_subset = list(feature_subset) if feature_subset else None
        feature_limit = mode_cfg.get("feature_limit")
        if resolved_feature_subset is None and feature_limit:
            clipped = available_features[: int(feature_limit)]
            if clipped and len(clipped) < len(available_features):
                resolved_feature_subset = clipped

        resolved_date_range = date_range
        recent_trade_dates = mode_cfg.get("recent_trade_dates")
        if resolved_date_range is None and recent_trade_dates:
            resolved_date_range = self._resolve_recent_date_range(
                feature_set_id,
                int(recent_trade_dates),
            )

        feature_count = len(resolved_feature_subset) if resolved_feature_subset else len(available_features)

        return {
            "mode": mode_name,
            "description": mode_cfg.get("description", ""),
            "feature_subset": resolved_feature_subset,
            "feature_count": feature_count,
            "available_feature_count": len(available_features),
            "date_range": resolved_date_range,
            "recent_trade_dates": recent_trade_dates,
            "feature_limit": feature_limit,
            "backtest_overrides": dict(mode_cfg.get("backtest_overrides", {})),
            "feature_set_id": feature_set_id,
            "label_set_id": label_set_id,
        }

    # --------------------------------------------------
    # 核心：构建回测/训练集
    # --------------------------------------------------
    def build_train_dataset(
        self,
        label_name: str | None = None,
        feature_subset: list[str] | None = None,
        include_tradeability: bool = True,
        include_backtest_cols: bool = True,
        feature_set_id: str | None = None,
        label_set_id: str | None = None,
        *,
        date_range: tuple[str, str] | None = None,
        runtime_mode: str | None = None,
        skip_pair_validation: bool = False,
        max_missing_ratio: float = 0.0,
    ) -> pd.DataFrame:
        """
        拼装完整的训练/回测数据集。

        v2 Phase E: 支持 feature_set_id / label_set_id 指定版本化表。
        SQLite 模式下使用 SQL JOIN，否则回退 pandas merge。
        构建前执行 feature/label 配对校验 (除非 skip_pair_validation=True)。
        """
        runtime_plan = self.resolve_train_runtime_plan(
            feature_set_id=feature_set_id,
            label_set_id=label_set_id,
            runtime_mode=runtime_mode,
            feature_subset=feature_subset,
            date_range=date_range,
        )

        resolved_feature_subset = runtime_plan["feature_subset"]
        resolved_date_range = runtime_plan["date_range"]

        if not skip_pair_validation:
            self.validate_feature_label_pair(
                feature_set_id=feature_set_id,
                label_set_id=label_set_id,
                date_range=resolved_date_range,
                max_missing_ratio=max_missing_ratio,
            )

        feature_scope = (
            f"{runtime_plan['feature_count']}/{runtime_plan['available_feature_count']}"
            if runtime_plan["available_feature_count"]
            else "0/0"
        )
        date_scope = (
            f"{resolved_date_range[0]} ~ {resolved_date_range[1]}"
            if resolved_date_range
            else "full"
        )
        print(
            "[MODE] DatasetBuilder "
            f"runtime_mode={runtime_plan['mode']} "
            f"feature_scope={feature_scope} "
            f"date_scope={date_scope}"
        )

        if self._use_db():
            df = self._build_train_sql(
                label_name, resolved_feature_subset,
                include_tradeability, include_backtest_cols,
                feature_set_id, label_set_id,
                date_range=resolved_date_range,
            )
        else:
            df = self._build_train_pandas(
                label_name, resolved_feature_subset,
                include_tradeability, include_backtest_cols,
                date_range=resolved_date_range,
            )

        df.attrs["dataset_runtime_plan"] = runtime_plan
        return df

    def _build_train_sql(
        self,
        label_name: str | None,
        feature_subset: list[str] | None,
        include_tradeability: bool,
        include_backtest_cols: bool,
        feature_set_id: str | None = None,
        label_set_id: str | None = None,
        *,
        date_range: tuple[str, str] | None = None,
    ) -> pd.DataFrame:
        """使用 SQLite SQL JOIN 构建训练集"""
        from src.data_layer.db import get_connection, table_exists
        con = get_connection(self.cfg)

        feat_table, label_table = self._resolve_table_names(feature_set_id, label_set_id)

        # 确定 feature 列
        if feature_subset:
            feat_cols = feature_subset
        else:
            feat_cols = self._list_available_feature_columns(feature_set_id)

        # 确定 label 列
        if label_name:
            label_cols = [label_name]
        else:
            label_cols = self._list_available_label_columns(label_set_id)

        # 构建 SELECT
        select_parts = ["f.date", "f.code", "f.industry"]
        select_parts += [f'f."{c}"' for c in feat_cols]
        select_parts += [f'l."{c}"' for c in label_cols]

        # JOIN daily_bar for tradeability / backtest cols
        has_daily = table_exists(self.cfg, "daily_bar")
        if has_daily and (include_tradeability or include_backtest_cols):
            if include_tradeability:
                select_parts += ["d.isST", "d.tradestatus"]
            if include_backtest_cols:
                select_parts += ["d.raw_pctChg AS raw_pctChg_d", "d.raw_amount"]

        select_str = ", ".join(select_parts)

        sql = f"""
            SELECT {select_str}
            FROM {feat_table} f
            INNER JOIN {label_table} l ON f.date = l.date AND f.code = l.code
        """
        params = []
        if has_daily and (include_tradeability or include_backtest_cols):
            sql += "  LEFT JOIN daily_bar d ON f.date = d.date AND f.code = d.code\n"
        if date_range:
            sql += "  WHERE f.date >= ? AND f.date <= ?\n"
            params.extend([date_range[0], date_range[1]])
        sql += "  ORDER BY f.code, f.date"

        df = con.execute(sql, params).df()
        df["date"] = pd.to_datetime(df["date"])

        # 重命名避免冲突
        if "raw_pctChg_d" in df.columns:
            if "raw_pctChg" not in df.columns:
                df = df.rename(columns={"raw_pctChg_d": "raw_pctChg"})
            else:
                df = df.drop(columns=["raw_pctChg_d"])

        return df.reset_index(drop=True)

    def _build_train_pandas(
        self,
        label_name: str | None,
        feature_subset: list[str] | None,
        include_tradeability: bool,
        include_backtest_cols: bool,
        *,
        date_range: tuple[str, str] | None = None,
    ) -> pd.DataFrame:
        """Pandas merge 构建训练集 (fallback)"""
        feat_df = self.feature_store.load(
            feature_subset=feature_subset,
            date_range=date_range,
        )
        label_df = self.label_store.load(
            label_name=label_name,
            date_range=date_range,
        )
        df = feat_df.merge(label_df, on=["date", "code"], how="inner")

        if include_tradeability or include_backtest_cols:
            canonical_df = self.canonical.load_daily()
            inject_cols = ["date", "code"]
            if include_tradeability:
                for c in ["isST", "tradestatus"]:
                    if c in canonical_df.columns:
                        inject_cols.append(c)
            if include_backtest_cols:
                for c in ["raw_pctChg", "raw_amount"]:
                    if c in canonical_df.columns:
                        inject_cols.append(c)
            inject_cols = list(dict.fromkeys(inject_cols))
            inject_df = canonical_df[inject_cols]
            existing = set(df.columns) - {"date", "code"}
            new_cols = [c for c in inject_df.columns if c not in existing or c in ("date", "code")]
            df = df.merge(inject_df[new_cols], on=["date", "code"], how="left")

        return df.sort_values(["code", "date"]).reset_index(drop=True)

    # --------------------------------------------------
    # 构建因子分析集
    # --------------------------------------------------
    def build_analysis_dataset(
        self,
        label_name: str | None = None,
        feature_subset: list[str] | None = None,
        feature_set_id: str | None = None,
        label_set_id: str | None = None,
        *,
        skip_pair_validation: bool = False,
        max_missing_ratio: float = 0.0,
    ) -> pd.DataFrame:
        """拼装因子分析用数据集 = features + labels，不含回测辅助列。"""
        if label_name and not skip_pair_validation:
            self.validate_feature_label_pair(
                feature_set_id=feature_set_id,
                label_set_id=label_set_id,
                max_missing_ratio=max_missing_ratio,
            )
        if self._use_db() and label_name:
            from src.data_layer.db import get_connection
            con = get_connection(self.cfg)

            feat_table, label_table = self._resolve_table_names(feature_set_id, label_set_id)

            if feature_subset:
                feat_cols = feature_subset
            else:
                feat_cols = self.feature_store.list_features()

            select_parts = ["f.date", "f.code", "f.industry"]
            select_parts += [f'f."{c}"' for c in feat_cols]
            select_parts += [f'l."{label_name}"']
            select_str = ", ".join(select_parts)

            sql = f"""
                SELECT {select_str}
                FROM {feat_table} f
                INNER JOIN {label_table} l ON f.date = l.date AND f.code = l.code
                ORDER BY f.code, f.date
            """
            df = con.execute(sql).df()
            df["date"] = pd.to_datetime(df["date"])
            return df

        # Pandas fallback
        feat_df = self.feature_store.load(feature_subset=feature_subset)
        if label_name:
            label_df = self.label_store.load(label_name=label_name)
            df = feat_df.merge(label_df, on=["date", "code"], how="inner")
        else:
            df = feat_df
        return df

    # --------------------------------------------------
    # 兼容性：生成旧格式合并文件 (过渡用)
    # --------------------------------------------------
    def build_legacy_merged(
        self,
        cfg: dict,
        output_path: str | None = None,
    ) -> pd.DataFrame:
        """
        [过渡兼容] 生成等价于旧 run_feature_pipeline() 产出的合并 parquet。

        这个方法存在的唯一目的是让 Dashboard 和旧代码路径不立刻 break。
        后续 Dashboard 应直接消费 FeatureStore + LabelStore，届时可删除本方法。
        """
        df = self.build_train_dataset(
            label_name=cfg["label"]["name"],
            include_tradeability=True,
            include_backtest_cols=True,
        )
        if output_path:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            df.to_parquet(output_path, index=False, engine="pyarrow")
            print(f"[PKG] [兼容] 合并数据集落盘: {output_path}  ({df.shape[0]} 行 x {df.shape[1]} 列)")
        return df
