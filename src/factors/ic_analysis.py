"""
因子有效性分析模块
==================
提供四类分析工具，均可独立调用，也可通过 run_ic_analysis() 一键全跑：

1. compute_ic_series()  -- 每日截面 Spearman IC，返回 (date x factor) DataFrame
2. compute_icir()       -- IC 均值 / IC 标准差，返回汇总 Series
3. compute_ic_decay()   -- IC Decay 曲线 (lag 1..max_lag)，返回 (lag x factor) DataFrame
4. factor_correlation() -- 因子 IC 时间序列的相关矩阵

结果均以 Parquet 落盘（路径由 analysis 配置节指定）。
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


# ====================================================
# 工具：截面 Spearman IC
# ====================================================
def _cross_ic(group: pd.DataFrame, features: list[str], label_col: str) -> pd.Series:
    """单个截面日的因子 IC（Spearman 相关系数）"""
    y = group[label_col]
    ic_vals = {}
    for f in features:
        x = group[f]
        valid = x.notna() & y.notna()
        if valid.sum() < 5:
            ic_vals[f] = np.nan
        else:
            ic_vals[f], _ = spearmanr(x[valid], y[valid])
    return pd.Series(ic_vals)


def compute_ic_series(
    df: pd.DataFrame,
    features: list[str],
    label_col: str,
) -> pd.DataFrame:
    """
    每个截面日计算各因子与标签的 Spearman IC。

    Returns
    -------
    ic_df : DataFrame, index=date, columns=features
    """
    print(f"[CALC] 计算 IC 时间序列:  {len(df['date'].unique())} 个截面日 x {len(features)} 个因子")
    ic_rows = (
        df.groupby("date")
        .apply(lambda g: _cross_ic(g, features, label_col), include_groups=False)
    )
    ic_df = ic_rows.astype("float32")
    ic_df.index = pd.to_datetime(ic_df.index)
    return ic_df


# ====================================================
# ICIR
# ====================================================
def compute_icir(ic_df: pd.DataFrame) -> pd.DataFrame:
    """
    汇总 IC 统计：IC_mean, IC_std, ICIR, IC>0_ratio。

    Returns
    -------
    summary : DataFrame, index=factor, columns=[ic_mean, ic_std, icir, pos_ratio]
    """
    summary = pd.DataFrame(
        {
            "ic_mean":   ic_df.mean(),
            "ic_std":    ic_df.std(),
            "icir":      ic_df.mean() / ic_df.std().replace(0, np.nan),
            "pos_ratio": (ic_df > 0).mean(),
        }
    )
    summary.index.name = "factor"
    return summary.sort_values("icir", ascending=False)


# ====================================================
# IC Decay
# ====================================================
def compute_ic_decay(
    df: pd.DataFrame,
    features: list[str],
    label_col: str,
    max_lag: int = 10,
) -> pd.DataFrame:
    """
    计算 IC 衰减曲线：在当日特征与 lag 期后标签之间的 IC。

    实现思路：
      - lag=1 即当日特征 vs 下期标签（即基础 IC）
      - lag=k 即当日特征 vs k 期后标签
      - 用 code 分组对标签做 shift，近似实现多期 horizon IC

    Returns
    -------
    decay_df : DataFrame, index=lag(1..max_lag), columns=features
    """
    print(f"[IC] 计算 IC Decay (lag 1..{max_lag})")
    records = {}
    df = df.sort_values(["code", "date"])

    for lag in range(1, max_lag + 1):
        # 将标签向前移动 lag 期 (用当期特征预测 lag 期后收益)
        shifted_label = df.groupby("code")[label_col].shift(-lag)
        tmp = df[features].copy()
        tmp["_label_shifted"] = shifted_label.values
        valid = tmp["_label_shifted"].notna()
        tmp = tmp[valid]
        if len(tmp) < 50:
            records[lag] = pd.Series(np.nan, index=features)
            continue
        ic_row = {}
        y = tmp["_label_shifted"]
        for f in features:
            x = tmp[f]
            both_valid = x.notna() & y.notna()
            if both_valid.sum() < 5:
                ic_row[f] = np.nan
            else:
                ic_row[f], _ = spearmanr(x[both_valid], y[both_valid])
        records[lag] = pd.Series(ic_row)

    decay_df = pd.DataFrame(records).T  # (lag x feature)
    decay_df.index.name = "lag"
    return decay_df.astype("float32")


# ====================================================
# 因子相关性矩阵
# ====================================================
def factor_correlation(ic_df: pd.DataFrame) -> pd.DataFrame:
    """
    基于 IC 时间序列的因子相关矩阵（Pearson）。
    高相关 (|r|>0.7) 的因子对信息冗余，可考虑合并或剔除。

    Returns
    -------
    corr : DataFrame (factor x factor)
    """
    return ic_df.corr(method="pearson").astype("float32")


# ====================================================
# 一键全跑
# ====================================================
def run_ic_analysis(cfg: dict, feature_set_id: str | None = None, label_set_id: str | None = None) -> dict:
    """
    加载特征矩阵 -> 计算 IC/ICIR/Decay/相关矩阵 -> 落盘 (Parquet + SQLite)。

    v2 Phase E: 优先通过 DatasetBuilder 获取数据，回退到旧路径 Parquet。
    如果提供 feature_set_id / label_set_id，使用版本化表。

    Returns
    -------
    dict with keys: ic_df, summary, decay_df, corr_df
    """
    label_col = cfg["label"]["name"]
    ana_cfg = cfg.get("analysis", {})
    max_lag = ana_cfg.get("ic_max_lag", 10)

    # 优先用 DatasetBuilder
    df = None
    try:
        from src.data_layer import DatasetBuilder
        builder = DatasetBuilder.from_config(cfg)
        if builder._use_db():
            df = builder.build_analysis_dataset(
                label_name=label_col,
                feature_set_id=feature_set_id,
                label_set_id=label_set_id,
            )
            print(f"[LOAD] [DatasetBuilder] 因子分析数据集: {df.shape[0]} 行 x {df.shape[1]} 列")
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("DatasetBuilder 加载失败，回退 Parquet: %s", exc)

    if df is None or df.empty:
        feat_path = cfg["features"]["output"]
        print(f"[LOAD] [兼容] 加载特征矩阵: {feat_path}")
        df = pd.read_parquet(feat_path)
        df["date"] = pd.to_datetime(df["date"])

    features = [c for c in df.columns if c.startswith("feat_")]

    # 1. IC 时间序列
    ic_df = compute_ic_series(df, features, label_col)
    _save(ic_df, ana_cfg.get("ic_output", "data/features/ic_series.parquet"), reset_index=True)

    # 2. ICIR 汇总
    summary = compute_icir(ic_df)
    _save(summary, ana_cfg.get("icir_output", "data/features/icir.parquet"), reset_index=True)

    # 3. IC Decay
    decay_df = compute_ic_decay(df, features, label_col, max_lag=max_lag)
    _save(decay_df, ana_cfg.get("ic_decay_output", "data/features/ic_decay.parquet"), reset_index=True)

    # 4. 相关矩阵 (不落盘，仅返回)
    corr_df = factor_correlation(ic_df)

    # 5. SQLite 持久化 IC 分析结果
    try:
        from src.data_layer.db import save_ic_analysis_results
        from src.data_layer.asset_id import make_config_hash
        analysis_id = f"ic__{make_config_hash(cfg.get('features', {}))[:12]}"
        save_ic_analysis_results(
            cfg, analysis_id, ic_df, summary,
            feature_set_id=feature_set_id,
        )
        print(f"[DB] IC 分析结果 -> SQLite (analysis_id={analysis_id})")
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("IC 分析结果 SQLite 写入失败: %s", exc)

    # 打印 Top 10 ICIR
    print("\n[TOP] ICIR Top 10 因子:")
    print(summary.head(10).to_string())
    print(f"\n[OK] IC 分析完成: IC={ic_df.shape}, Decay lags={max_lag}")

    return {"ic_df": ic_df, "summary": summary, "decay_df": decay_df, "corr_df": corr_df}


def _save(df: pd.DataFrame, path: str, reset_index: bool = False) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    out = df.reset_index() if reset_index else df
    out.to_parquet(path, index=False, engine="pyarrow")
    print(f"  [SAVE] 已保存: {path}  {df.shape}")
