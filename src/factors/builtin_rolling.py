"""内置因子组：Alpha158 滚动窗口矩阵族 (每窗口 17 个因子)"""
import logging
import time

import numpy as np
import pandas as pd

from src.registry import registry, FactorMeta

logger = logging.getLogger(__name__)


# ====================================================
# 辅助算子
# ====================================================
def _rolling_pct_rank(y):
    """窗口内末尾元素的百分位排名 (纯 numpy, 替代 pd.Series.rank)"""
    return np.searchsorted(np.sort(y), y[-1], side="right") / len(y)


def _calc_exact_ols(grouped, col_name: str, d: int):
    """滚动窗口 OLS: BETA(斜率), RSQR(拟合优度), RESI(残差)

    使用累积和技巧避免 rolling.apply, 纯向量化计算 E(XY):
    WS_t = S_t + d * C_t - rolling_sum_d(C_t)
    其中 S_t=rolling_sum(y,d), C_t=cumsum(y), 再除以 d 得 E(XY)。
    """
    x_mean = (d + 1) / 2
    x_var = (d ** 2 - 1) / 12

    y_mean = grouped[col_name].transform(lambda y: y.rolling(d).mean())
    y_var = grouped[col_name].transform(lambda y: y.rolling(d).var(ddof=0))

    # E(XY) 向量化: WS_t = S_t + d * C_t - RS(C)_t
    rolling_sum_y = grouped[col_name].transform(lambda y: y.rolling(d).sum())
    cumsum_y = grouped[col_name].cumsum()
    rolling_sum_cumsum = cumsum_y.groupby(grouped.obj["code"]).transform(
        lambda c: c.rolling(d).sum()
    )
    e_xy = (rolling_sum_y + d * cumsum_y - rolling_sum_cumsum) / d

    cov_xy = e_xy - x_mean * y_mean
    beta = cov_xy / x_var
    alpha_hat = y_mean - beta * x_mean
    rsqr = ((cov_xy ** 2) / (x_var * y_var + 1e-12)).clip(0, 1)

    current_y = grouped.obj[col_name]
    resi = (current_y - (alpha_hat + beta * d)) / (current_y + 1e-12)

    return beta.astype("float32"), rsqr.astype("float32"), resi.astype("float32")


# ====================================================
# 注册：滚动窗口因子
# ====================================================
@registry.register_factor("rolling", meta=FactorMeta(
    group="rolling",
    input_cols=["raw_close", "raw_high", "raw_low", "raw_volume", "raw_pctChg"],
    output_cols=["feat_ROC", "feat_MA", "feat_STD", "feat_EMA",
                 "feat_MAX", "feat_MIN", "feat_RSV",
                 "feat_IMAX", "feat_IMIN", "feat_RANK",
                 "feat_VMA", "feat_VSTD", "feat_WVMA", "feat_CORR",
                 "feat_BETA", "feat_RSQR", "feat_RESI"],
    description="Alpha158 滚动窗口因子: 动量/极值/量价/OLS (每窗口17个)",
    windowed=True,
))
def rolling_factors(
    df: pd.DataFrame, grouped, windows: list[int], f32: str
) -> tuple[pd.DataFrame, list[str]]:
    """标准 Alpha158 滚动窗口因子：动量/极值/量价/OLS"""
    features: list[str] = []

    for d in windows:
        t_win = time.time()

        # --- 动量、趋势、波动 ---
        df[f"feat_ROC{d}"] = grouped["_close_adj"].transform(
            lambda x: x.shift(d) / x - 1
        ).astype(f32)

        # 复用 rolling mean (VMA/WVMA/CORR 都需要)
        _close_roll_mean = grouped["_close_adj"].transform(
            lambda x: x.rolling(d).mean()
        )
        df[f"feat_MA{d}"] = (_close_roll_mean / df["_close_adj"] - 1).astype(f32)

        df[f"feat_STD{d}"] = grouped["raw_pctChg"].transform(
            lambda x: x.rolling(d).std()
        ).astype(f32)
        df[f"feat_EMA{d}"] = grouped["_close_adj"].transform(
            lambda x: x.ewm(span=d).mean() / x - 1
        ).astype(f32)

        # --- 极值与分位 ---
        roll_max = grouped["_high_adj"].transform(lambda x: x.rolling(d).max())
        roll_min = grouped["_low_adj"].transform(lambda x: x.rolling(d).min())
        df[f"feat_MAX{d}"] = (roll_max / df["_close_adj"] - 1).astype(f32)
        df[f"feat_MIN{d}"] = (roll_min / df["_close_adj"] - 1).astype(f32)
        df[f"feat_RSV{d}"] = (
            (df["_close_adj"] - roll_min) / (roll_max - roll_min + 1e-10)
        ).astype(f32)
        df[f"feat_IMAX{d}"] = grouped["_high_adj"].transform(
            lambda x: x.rolling(d).apply(np.argmax, raw=True) / d
        ).astype(f32)
        df[f"feat_IMIN{d}"] = grouped["_low_adj"].transform(
            lambda x: x.rolling(d).apply(np.argmin, raw=True) / d
        ).astype(f32)
        # RANK: 纯 numpy 百分位排名 (替代 pd.Series.rank 重开销)
        df[f"feat_RANK{d}"] = grouped["_close_adj"].transform(
            lambda x: x.rolling(d).apply(_rolling_pct_rank, raw=True)
        ).astype(f32)

        # --- 成交量 (复用 rolling mean) ---
        _vol_roll_mean = grouped["raw_volume"].transform(
            lambda x: x.rolling(d).mean()
        )
        df[f"feat_VMA{d}"] = (
            _vol_roll_mean / (df["raw_volume"] + 1e-10)
        ).astype(f32)
        df[f"feat_VSTD{d}"] = (
            grouped["raw_volume"].transform(lambda x: x.rolling(d).std())
            / (_vol_roll_mean + 1e-10)
        ).astype(f32)
        df[f"feat_WVMA{d}"] = (
            (df["_close_adj"] * df["raw_volume"]).groupby(df["code"]).transform(
                lambda x: x.rolling(d).mean()
            ) / (_close_roll_mean * _vol_roll_mean + 1e-10)
        ).astype(f32)

        # CORR: 用协方差公式避免 grouped.apply 兼容性问题
        _vlog_roll_mean = grouped["_vol_log"].transform(lambda x: x.rolling(d).mean())
        _xy = (df["_close_adj"] * df["_vol_log"]).groupby(df["code"]).transform(
            lambda x: x.rolling(d).mean()
        )
        _x_std = grouped["_close_adj"].transform(lambda x: x.rolling(d).std())
        _y_std = grouped["_vol_log"].transform(lambda x: x.rolling(d).std())
        df[f"feat_CORR{d}"] = (
            (_xy - _close_roll_mean * _vlog_roll_mean) / (_x_std * _y_std + 1e-10)
        ).astype(f32)

        # --- OLS (向量化, 无 rolling.apply) ---
        b, r, e = _calc_exact_ols(grouped, "_close_adj", d)
        df[f"feat_BETA{d}"] = (b / (df["_close_adj"] + 1e-10)).astype(f32)
        df[f"feat_RSQR{d}"] = r
        df[f"feat_RESI{d}"] = e

        features.extend([
            f"feat_ROC{d}", f"feat_MA{d}", f"feat_STD{d}", f"feat_EMA{d}",
            f"feat_MAX{d}", f"feat_MIN{d}", f"feat_RSV{d}",
            f"feat_IMAX{d}", f"feat_IMIN{d}", f"feat_RANK{d}",
            f"feat_VMA{d}", f"feat_VSTD{d}", f"feat_WVMA{d}", f"feat_CORR{d}",
            f"feat_BETA{d}", f"feat_RSQR{d}", f"feat_RESI{d}",
        ])

        del roll_max, roll_min, b, r, e
        del _close_roll_mean, _vol_roll_mean, _vlog_roll_mean, _xy, _x_std, _y_std
        logger.info("[rolling] window=%d elapsed=%.1fs", d, time.time() - t_win)

    return df, features
