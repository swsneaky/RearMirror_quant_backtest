"""
扩展滚动窗口因子 -- Alpha158 补全 (每窗口 12 个因子)
==================================================
QTLU / QTLD -- 分位数偏离
CORD       -- 价量变化率相关性
CNTP / CNTN / CNTD -- 正负收益日占比
SUMP / SUMN / SUMD -- 正负收益累加
VSUMP / VSUMN / VSUMD -- 条件成交量占比
"""
import logging
import time

import numpy as np
import pandas as pd

from src.registry import registry, FactorMeta

logger = logging.getLogger(__name__)


@registry.register_factor("rolling_ext", meta=FactorMeta(
    group="rolling_ext",
    input_cols=["raw_close", "raw_volume", "raw_pctChg"],
    output_cols=["feat_QTLU", "feat_QTLD", "feat_CORD",
                 "feat_CNTP", "feat_CNTN", "feat_CNTD",
                 "feat_SUMP", "feat_SUMN", "feat_SUMD",
                 "feat_VSUMP", "feat_VSUMN", "feat_VSUMD"],
    description="Alpha158 滚动窗口补全: 分位数/正负收益统计/条件量 (每窗口12个)",
    windowed=True,
))
def rolling_ext_factors(
    df: pd.DataFrame, grouped, windows: list[int], f32: str
) -> tuple[pd.DataFrame, list[str]]:
    """Alpha158 滚动窗口补全：分位数、正负收益统计、条件量"""
    features: list[str] = []

    # 临时辅助列：按日收益方向拆分成交量
    df["_pos_vol"] = (df["raw_volume"] * (df["raw_pctChg"] > 0)).astype(float)
    df["_neg_vol"] = (df["raw_volume"] * (df["raw_pctChg"] < 0)).astype(float)

    # 预计算每个窗口复用的 diff 序列 (只需计算一次)
    _dx = grouped["_close_adj"].transform(lambda x: x.diff())
    _dy = grouped["_vol_log"].transform(lambda x: x.diff())
    # 预计算正/负收益用于 SUMP/SUMN
    _pctchg_pos = df["raw_pctChg"].clip(lower=0)
    _pctchg_neg = (-df["raw_pctChg"]).clip(lower=0)

    for d in windows:
        t_win = time.time()

        # ---- 分位数偏离 ----
        df[f"feat_QTLU{d}"] = (
            grouped["_close_adj"].transform(
                lambda x: x.rolling(d).quantile(0.8)
            ) / df["_close_adj"] - 1
        ).astype(f32)
        df[f"feat_QTLD{d}"] = (
            grouped["_close_adj"].transform(
                lambda x: x.rolling(d).quantile(0.2)
            ) / df["_close_adj"] - 1
        ).astype(f32)

        # ---- 价量变化率相关性 (CORD) ----
        _dxy_mean = (_dx * _dy).groupby(df["code"]).transform(
            lambda x: x.rolling(d).mean()
        )
        _dx_mean = _dx.groupby(df["code"]).transform(lambda x: x.rolling(d).mean())
        _dy_mean = _dy.groupby(df["code"]).transform(lambda x: x.rolling(d).mean())
        _dx_std = _dx.groupby(df["code"]).transform(lambda x: x.rolling(d).std())
        _dy_std = _dy.groupby(df["code"]).transform(lambda x: x.rolling(d).std())
        df[f"feat_CORD{d}"] = (
            (_dxy_mean - _dx_mean * _dy_mean) / (_dx_std * _dy_std + 1e-10)
        ).astype(f32)

        # ---- 正负收益日占比 ----
        df[f"feat_CNTP{d}"] = grouped["raw_pctChg"].transform(
            lambda x: (x > 0).rolling(d).sum() / d
        ).astype(f32)
        df[f"feat_CNTN{d}"] = grouped["raw_pctChg"].transform(
            lambda x: (x < 0).rolling(d).sum() / d
        ).astype(f32)
        df[f"feat_CNTD{d}"] = (
            df[f"feat_CNTP{d}"] - df[f"feat_CNTN{d}"]
        ).astype(f32)

        # ---- 正负收益累加 (使用预计算的 clip 序列) ----
        df[f"feat_SUMP{d}"] = (
            _pctchg_pos.groupby(df["code"]).transform(
                lambda x: x.rolling(d).sum()
            ) / d
        ).astype(f32)
        df[f"feat_SUMN{d}"] = (
            _pctchg_neg.groupby(df["code"]).transform(
                lambda x: x.rolling(d).sum()
            ) / d
        ).astype(f32)
        df[f"feat_SUMD{d}"] = (
            df[f"feat_SUMP{d}"] - df[f"feat_SUMN{d}"]
        ).astype(f32)

        # ---- 条件成交量占比 ----
        tot_vol = grouped["raw_volume"].transform(
            lambda x: x.rolling(d).sum()
        )
        # _pos_vol/_neg_vol 是本函数创建的临时列，不在 grouped 的原始 DataFrame 中
        # (checkpoint merge 后 grouped 引用旧对象)，因此用 df.groupby 重新分组
        df[f"feat_VSUMP{d}"] = (
            df["_pos_vol"].groupby(df["code"]).transform(lambda x: x.rolling(d).sum())
            / (tot_vol + 1e-10)
        ).astype(f32)
        df[f"feat_VSUMN{d}"] = (
            df["_neg_vol"].groupby(df["code"]).transform(lambda x: x.rolling(d).sum())
            / (tot_vol + 1e-10)
        ).astype(f32)
        df[f"feat_VSUMD{d}"] = (
            df[f"feat_VSUMP{d}"] - df[f"feat_VSUMN{d}"]
        ).astype(f32)

        features.extend([
            f"feat_QTLU{d}", f"feat_QTLD{d}", f"feat_CORD{d}",
            f"feat_CNTP{d}", f"feat_CNTN{d}", f"feat_CNTD{d}",
            f"feat_SUMP{d}", f"feat_SUMN{d}", f"feat_SUMD{d}",
            f"feat_VSUMP{d}", f"feat_VSUMN{d}", f"feat_VSUMD{d}",
        ])

        del tot_vol
        logger.info("[rolling_ext] window=%d elapsed=%.1fs", d, time.time() - t_win)

    return df, features
