"""
实验结果存储协议 -- 标准化回测产物落盘

职责：
  - 定义一次回测实验应稳定产出的全部资产
  - 提供统一的落盘和读取接口 (SQLite + 文件系统双写)
  - 让 Dashboard / 分析脚本只依赖这套协议，不依赖回测引擎内部细节

一次实验的标准产物：
  predictions.parquet    -- 每期每股预测得分 (date, code, pred_score, pred_rank, label, selected)
  holdings.parquet       -- 每期持仓快照 (date, code, weight, is_new, is_exit)
  nav_daily.parquet      -- 每期净值曲线 (date, nav, bench_nav, excess_nav, cost, turnover)
  metrics_summary.json   -- 汇总指标 (ann_return, sharpe, max_dd, ...)
  config_snapshot.yaml   -- 本次实验的完整配置快照
  models/                -- 模型制品
  analysis/              -- 因子分析产物

SQLite 表 (以 experiment_id 分区):
  predictions, holdings, nav_daily, metrics_summary
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class ExperimentArtifacts:
    """一次回测实验产出的全部标准资产路径"""
    base_dir: str
    predictions_path: str = ""
    holdings_path: str = ""
    nav_path: str = ""
    metrics_path: str = ""
    config_path: str = ""
    models_dir: str = ""
    analysis_dir: str = ""

    def __post_init__(self):
        results = os.path.join(self.base_dir, "results")
        self.predictions_path = self.predictions_path or os.path.join(results, "predictions.parquet")
        self.holdings_path = self.holdings_path or os.path.join(results, "holdings.parquet")
        self.nav_path = self.nav_path or os.path.join(results, "nav_daily.parquet")
        self.metrics_path = self.metrics_path or os.path.join(results, "metrics_summary.json")
        self.config_path = self.config_path or os.path.join(self.base_dir, "config_snapshot.yaml")
        self.models_dir = self.models_dir or os.path.join(self.base_dir, "models")
        self.analysis_dir = self.analysis_dir or os.path.join(self.base_dir, "analysis")


class ExperimentStore:
    """
    实验结果统一落盘器 -- 文件系统 + SQLite 双写。

    用法：
        store = ExperimentStore("experiments/tasks/20260331_xgb", cfg=cfg)
        store.save_predictions(results_df)
        store.save_holdings(holdings_df)
        store.save_nav(nav_df)
        store.save_metrics(metrics_dict)

        # 读取
        pred = store.load_predictions()
        metrics = store.load_metrics()
    """

    def __init__(self, base_dir: str = "data/results", cfg: dict | None = None):
        self.artifacts = ExperimentArtifacts(base_dir=base_dir)
        self.cfg = cfg or {}
        self.experiment_id = os.path.basename(os.path.normpath(base_dir))
        self._feature_set_id: str | None = None
        self._label_set_id: str | None = None
        self._ensure_dirs()

    def set_lineage(
        self,
        feature_set_id: str | None = None,
        label_set_id: str | None = None,
    ) -> None:
        """设置本次实验关联的数据资产 ID (供 pipeline 调用)"""
        self._feature_set_id = feature_set_id
        self._label_set_id = label_set_id

    def _ensure_dirs(self):
        for d in [
            os.path.dirname(self.artifacts.predictions_path),
            self.artifacts.models_dir,
            self.artifacts.analysis_dir,
        ]:
            os.makedirs(d, exist_ok=True)

    def _get_db_con(self):
        """尝试获取 SQLite 连接，失败返回 None"""
        if not self.cfg:
            return None
        try:
            from src.data_layer.db import get_connection
            return get_connection(self.cfg)
        except Exception as exc:
            logger.warning("ExperimentStore SQLite 连接失败，回退文件系统: %s", exc)
            return None

    # --------------------------------------------------
    # 保存接口
    # --------------------------------------------------
    def save_predictions(self, df: pd.DataFrame) -> str:
        """保存预测结果 -> Parquet + SQLite"""
        df.to_parquet(self.artifacts.predictions_path, index=False, engine="pyarrow")
        print(f"[SAVE] predictions 落盘: {self.artifacts.predictions_path}  ({len(df)} 行)")

        con = self._get_db_con()
        if con is not None:
            try:
                # 准备 SQLite 写入数据
                db_df = df.copy()
                db_df["experiment_id"] = self.experiment_id
                # 映射列名到 SQLite schema
                col_map = {}
                for lc in db_df.columns:
                    if lc.startswith("label_"):
                        col_map[lc] = "label_value"
                db_df = db_df.rename(columns=col_map)
                # 只保留 SQLite schema 中存在的列
                db_cols = ["experiment_id", "date", "code", "pred_score", "pred_rank",
                           "selected", "label_value", "raw_pctChg", "cost_ratio", "turnover_ratio"]
                keep = [c for c in db_cols if c in db_df.columns]
                db_df = db_df[keep]
                # 删除旧数据再插入
                con.execute("DELETE FROM predictions WHERE experiment_id = ?", [self.experiment_id])
                con.df_to_table("predictions", db_df)
                print(f"[DB] predictions: {len(db_df)} 行 (id={self.experiment_id})")
            except Exception as e:
                print(f"[WARN] SQLite predictions 写入失败: {e}")
                logger.warning("SQLite predictions 写入失败: %s", e)

        return self.artifacts.predictions_path

    def save_holdings(self, df: pd.DataFrame) -> str:
        """保存持仓快照 -> Parquet + SQLite"""
        df.to_parquet(self.artifacts.holdings_path, index=False, engine="pyarrow")
        print(f"[SAVE] holdings 落盘: {self.artifacts.holdings_path}  ({len(df)} 行)")

        con = self._get_db_con()
        if con is not None:
            try:
                db_df = df.copy()
                db_df["experiment_id"] = self.experiment_id
                db_cols = ["experiment_id", "date", "code", "weight", "is_new", "is_exit"]
                keep = [c for c in db_cols if c in db_df.columns]
                db_df = db_df[keep]
                con.execute("DELETE FROM holdings WHERE experiment_id = ?", [self.experiment_id])
                con.df_to_table("holdings", db_df)
                print(f"[DB] holdings: {len(db_df)} 行 (id={self.experiment_id})")
            except Exception as e:
                print(f"[WARN] SQLite holdings 写入失败: {e}")
                logger.warning("SQLite holdings 写入失败: %s", e)

        return self.artifacts.holdings_path

    def save_nav(self, nav_df: pd.DataFrame) -> str:
        """保存净值序列 -> Parquet + SQLite"""
        nav_df.to_parquet(self.artifacts.nav_path, index=False, engine="pyarrow")
        print(f"[SAVE] nav_daily 落盘: {self.artifacts.nav_path}  ({len(nav_df)} 行)")

        con = self._get_db_con()
        if con is not None:
            try:
                db_df = nav_df.copy()
                db_df["experiment_id"] = self.experiment_id
                db_cols = ["experiment_id", "date", "nav", "bench_nav", "excess_nav",
                           "cost_ratio", "turnover_ratio"]
                keep = [c for c in db_cols if c in db_df.columns]
                db_df = db_df[keep]
                con.execute("DELETE FROM nav_daily WHERE experiment_id = ?", [self.experiment_id])
                con.df_to_table("nav_daily", db_df)
                print(f"[DB] nav_daily: {len(db_df)} 行 (id={self.experiment_id})")
            except Exception as e:
                print(f"[WARN] SQLite nav_daily 写入失败: {e}")
                logger.warning("SQLite nav_daily 写入失败: %s", e)

        return self.artifacts.nav_path

    def save_metrics(self, metrics: dict) -> str:
        """保存汇总指标 -> JSON + SQLite"""
        serializable = {}
        for k, v in metrics.items():
            if pd.api.types.is_scalar(v):
                serializable[k] = v.item() if hasattr(v, "item") else v
        with open(self.artifacts.metrics_path, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2, ensure_ascii=False, default=str)
        print(f"[SAVE] metrics 落盘: {self.artifacts.metrics_path}")

        con = self._get_db_con()
        if con is not None:
            try:
                row = {
                    "experiment_id": self.experiment_id,
                    "ann_return": serializable.get("ann_return"),
                    "ann_excess_return": serializable.get("ann_excess_return"),
                    "ann_volatility": serializable.get("ann_volatility"),
                    "tracking_error": serializable.get("tracking_error"),
                    "sharpe_ratio": serializable.get("sharpe_ratio"),
                    "information_ratio": serializable.get("information_ratio"),
                    "max_drawdown": serializable.get("max_drawdown"),
                    "excess_max_drawdown": serializable.get("excess_max_drawdown"),
                    "avg_turnover": serializable.get("avg_turnover"),
                    "avg_cost_per_period": serializable.get("avg_cost_per_period"),
                }
                db_df = pd.DataFrame([row])
                con.execute("DELETE FROM metrics_summary WHERE experiment_id = ?", [self.experiment_id])
                con.df_to_table("metrics_summary", db_df)
                print(f"[DB] metrics_summary: id={self.experiment_id}")
            except Exception as e:
                print(f"[WARN] SQLite metrics_summary 写入失败: {e}")
                logger.warning("SQLite metrics_summary 写入失败: %s", e)

        return self.artifacts.metrics_path

    def save_config(self, cfg: dict) -> str:
        """保存本次实验的完整配置快照"""
        import yaml
        with open(self.artifacts.config_path, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)
        return self.artifacts.config_path

    def register_run(self, cfg: dict | None = None) -> None:
        """
        在 experiment_run 表中注册本次实验的血缘信息。

        应在回测开始前调用；回测结束后调用 finish_run()。
        """
        con = self._get_db_con()
        if con is None:
            return
        try:
            from src.data_layer.db import register_experiment_run
            from src.data_layer.asset_id import make_config_hash
            import json

            run_cfg = cfg or self.cfg
            model_name = run_cfg.get("model", {}).get("active", "")
            model_params = run_cfg.get("model", {}).get(model_name, {})
            model_params_hash = make_config_hash(model_params) if model_params else None
            config_snapshot = json.dumps(run_cfg, default=str, ensure_ascii=False)

            register_experiment_run(
                run_cfg,
                experiment_id=self.experiment_id,
                feature_set_id=self._feature_set_id,
                label_set_id=self._label_set_id,
                model_name=model_name,
                model_params_hash=model_params_hash,
                config_snapshot=config_snapshot,
            )
            print(f"[DB] experiment_run 已注册: id={self.experiment_id}")
        except Exception as exc:
            logger.warning("experiment_run 注册失败: %s", exc)

    def finish_run(self, status: str = "done") -> None:
        """标记实验运行完成"""
        con = self._get_db_con()
        if con is None:
            return
        try:
            from src.data_layer.db import finish_experiment_run
            finish_experiment_run(self.cfg, self.experiment_id, status)
        except Exception as exc:
            logger.warning("experiment_run 完成标记失败: %s", exc)

    # --------------------------------------------------
    # 读取接口
    # --------------------------------------------------
    def load_predictions(self) -> pd.DataFrame | None:
        # 优先 SQLite
        con = self._get_db_con()
        if con is not None:
            try:
                df = con.execute(
                    "SELECT * FROM predictions WHERE experiment_id = ?",
                    [self.experiment_id],
                ).df()
                if len(df) > 0:
                    df["date"] = pd.to_datetime(df["date"])
                    return df
            except Exception as exc:
                logger.warning("SQLite predictions 读取失败，回退 Parquet: %s", exc)
        if os.path.exists(self.artifacts.predictions_path):
            return pd.read_parquet(self.artifacts.predictions_path)
        return None

    def load_holdings(self) -> pd.DataFrame | None:
        con = self._get_db_con()
        if con is not None:
            try:
                df = con.execute(
                    "SELECT * FROM holdings WHERE experiment_id = ?",
                    [self.experiment_id],
                ).df()
                if len(df) > 0:
                    df["date"] = pd.to_datetime(df["date"])
                    return df
            except Exception as exc:
                logger.warning("SQLite holdings 读取失败，回退 Parquet: %s", exc)
        if os.path.exists(self.artifacts.holdings_path):
            return pd.read_parquet(self.artifacts.holdings_path)
        return None

    def load_nav(self) -> pd.DataFrame | None:
        con = self._get_db_con()
        if con is not None:
            try:
                df = con.execute(
                    "SELECT * FROM nav_daily WHERE experiment_id = ?",
                    [self.experiment_id],
                ).df()
                if len(df) > 0:
                    df["date"] = pd.to_datetime(df["date"])
                    return df
            except Exception as exc:
                logger.warning("SQLite nav_daily 读取失败，回退 Parquet: %s", exc)
        if os.path.exists(self.artifacts.nav_path):
            return pd.read_parquet(self.artifacts.nav_path)
        return None

    def load_metrics(self) -> dict | None:
        con = self._get_db_con()
        if con is not None:
            try:
                df = con.execute(
                    "SELECT * FROM metrics_summary WHERE experiment_id = ?",
                    [self.experiment_id],
                ).df()
                if len(df) > 0:
                    return df.iloc[0].dropna().to_dict()
            except Exception as exc:
                logger.warning("SQLite metrics_summary 读取失败，回退 JSON: %s", exc)
        if os.path.exists(self.artifacts.metrics_path):
            with open(self.artifacts.metrics_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return None


# --------------------------------------------------
# 工具函数：从 backtest 结果构建 holdings DataFrame
# --------------------------------------------------
def build_holdings_from_predictions(
    results_df: pd.DataFrame,
    top_k: int,
) -> pd.DataFrame:
    """
    从预测结果构建每期持仓快照。

    Parameters
    ----------
    results_df : 包含 date, code, pred_score, selected 的回测结果
    top_k : 持仓数量

    Returns
    -------
    DataFrame: date, code, weight, is_new, is_exit
    """
    if "selected" in results_df.columns:
        held = results_df[results_df["selected"] == 1].copy()
    else:
        held = results_df.groupby("date").apply(
            lambda g: g.nlargest(top_k, "pred_score"), include_groups=False
        ).reset_index(drop=True)

    # 等权
    held["weight"] = held.groupby("date")["code"].transform(lambda x: 1.0 / len(x))

    # 标记新进/退出
    dates = sorted(held["date"].unique())
    prev_codes: set[str] = set()
    records = []
    for d in dates:
        day_codes = set(held.loc[held["date"] == d, "code"])
        for _, row in held[held["date"] == d].iterrows():
            records.append({
                "date": row["date"],
                "code": row["code"],
                "weight": row["weight"],
                "is_new": int(row["code"] not in prev_codes),
                "is_exit": 0,
            })
        # 标记退出（上期有、本期无）
        exited = prev_codes - day_codes
        for code in exited:
            records.append({
                "date": d,
                "code": code,
                "weight": 0.0,
                "is_new": 0,
                "is_exit": 1,
            })
        prev_codes = day_codes

    return pd.DataFrame(records)


def build_nav_from_metrics(
    metrics: dict,
    results_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    从 evaluate() 返回的 metrics 构建标准 nav_daily DataFrame。
    """
    nav_series = metrics.get("nav")
    bench_series = metrics.get("bench_nav")
    excess_series = metrics.get("excess_nav")

    if nav_series is None:
        return pd.DataFrame()

    nav_df = pd.DataFrame({"date": nav_series.index, "nav": nav_series.values})
    if bench_series is not None:
        nav_df["bench_nav"] = bench_series.reindex(nav_df["date"]).values
    if excess_series is not None:
        nav_df["excess_nav"] = excess_series.reindex(nav_df["date"]).values

    # 附加每期 cost/turnover
    if "cost_ratio" in results_df.columns:
        cost_per_date = results_df.groupby("date")["cost_ratio"].first()
        nav_df["cost_ratio"] = nav_df["date"].map(cost_per_date)
    if "turnover_ratio" in results_df.columns:
        to_per_date = results_df.groupby("date")["turnover_ratio"].first()
        nav_df["turnover_ratio"] = nav_df["date"].map(to_per_date)

    return nav_df
