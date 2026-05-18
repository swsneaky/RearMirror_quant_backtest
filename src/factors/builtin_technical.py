"""
技术指标因子 -- 经典技术分析指标
================================
基于现有 OHLCV + pctChg + amount 即可计算，无需额外数据源。

窗口因子 (每窗口 1 个):
  RSI, CCI, VWAP_BIAS  -> 3 x len(windows)

  已删除冗余:
    PSY  ≡ CNTP (rolling_ext)
    BIAS ≡ MA   (rolling, 树模型单调等价)
    WILLR ≡ 1-RSV (rolling, 树模型线性等价)

固定参数因子:
  MACD_DIF, MACD_DEA, MACD_HIST  (12/26/9)
  KDJ_K, KDJ_D, KDJ_J            (9/3/3)
  OBV, MFI14
"""
import logging
import time

import numpy as np
import pandas as pd

from src.registry import registry, FactorMeta

logger = logging.getLogger(__name__)


@registry.register_factor("technical", meta=FactorMeta(
    group="technical",
    input_cols=["raw_close", "raw_high", "raw_low", "raw_volume",
                "raw_amount", "raw_pctChg"],
    output_cols=["feat_RSI", "feat_CCI", "feat_VWAP_BIAS",
                 "feat_MACD_DIF", "feat_MACD_DEA", "feat_MACD_HIST",
                 "feat_KDJ_K", "feat_KDJ_D", "feat_KDJ_J",
                 "feat_OBV", "feat_MFI14"],
    description="经典技术分析指标: RSI/CCI/VWAP_BIAS/MACD/KDJ/OBV/MFI",
    windowed=True,
))
def technical_factors(
    df: pd.DataFrame, grouped, windows: list[int], f32: str
) -> tuple[pd.DataFrame, list[str]]:
    """经典技术分析指标"""
    features: list[str] = []

    # ================================================================
    # 窗口因子 (预计算不依赖窗口的中间量)
    # ================================================================
    # RSI 用: delta/gain/loss 不依赖窗口 d, 只需计算一次
    _delta = grouped["_close_adj"].transform(lambda x: x.diff())
    _gain = _delta.clip(lower=0)
    _loss = (-_delta).clip(lower=0)

    # CCI 用: TP (typical price) 不依赖窗口 d
    _tp = (df["_high_adj"] + df["_low_adj"] + df["_close_adj"]) / 3

    for d in windows:
        t_win = time.time()

        # ---- RSI (使用预计算的 gain/loss) ----
        avg_gain = _gain.groupby(df["code"]).transform(lambda x: x.rolling(d).mean())
        avg_loss = _loss.groupby(df["code"]).transform(lambda x: x.rolling(d).mean())
        df[f"feat_RSI{d}"] = (avg_gain / (avg_gain + avg_loss + 1e-10)).astype(f32)

        # ---- CCI: (TP - MA_TP) / (0.015 * MAD_TP) ----
        # MAD 使用 rolling.apply 近似: MAD ≈ rolling_std * sqrt(2/π) ≈ 0.7979 * std
        # 对树模型等价 (单调变换), 但避免 rolling.apply 的 Python 开销
        tp_ma = _tp.groupby(df["code"]).transform(lambda x: x.rolling(d).mean())
        tp_std = _tp.groupby(df["code"]).transform(lambda x: x.rolling(d).std())
        tp_mad_approx = tp_std * 0.7979  # MAD ≈ std * sqrt(2/π) for normal
        df[f"feat_CCI{d}"] = ((_tp - tp_ma) / (0.015 * tp_mad_approx + 1e-10)).astype(f32)

        # ---- VWAP_BIAS: (close - VWAP) / VWAP ----
        vwap = (
            grouped["raw_amount"].transform(lambda x: x.rolling(d).sum())
            / (grouped["raw_volume"].transform(lambda x: x.rolling(d).sum()) + 1e-10)
        )
        df[f"feat_VWAP_BIAS{d}"] = (
            (df["_close_adj"] - vwap) / (vwap + 1e-10)
        ).astype(f32)

        features.extend([
            f"feat_RSI{d}", f"feat_CCI{d}", f"feat_VWAP_BIAS{d}",
        ])
        logger.info("[technical] window=%d elapsed=%.1fs", d, time.time() - t_win)

    # ================================================================
    # 固定参数因子
    # ================================================================
    t_fixed = time.time()

    # ---- MACD (12, 26, 9) ----
    ema12 = grouped["_close_adj"].transform(lambda x: x.ewm(span=12).mean())
    ema26 = grouped["_close_adj"].transform(lambda x: x.ewm(span=26).mean())
    dif = ema12 - ema26
    dea = dif.groupby(df["code"]).transform(lambda x: x.ewm(span=9).mean())
    df["feat_MACD_DIF"] = (dif / (df["_close_adj"] + 1e-10)).astype(f32)
    df["feat_MACD_DEA"] = (dea / (df["_close_adj"] + 1e-10)).astype(f32)
    df["feat_MACD_HIST"] = (2 * (dif - dea) / (df["_close_adj"] + 1e-10)).astype(f32)

    # ---- KDJ (9, 3, 3) ----
    hh9 = grouped["_high_adj"].transform(lambda x: x.rolling(9).max())
    ll9 = grouped["_low_adj"].transform(lambda x: x.rolling(9).min())
    rsv = (df["_close_adj"] - ll9) / (hh9 - ll9 + 1e-10) * 100
    k = rsv.groupby(df["code"]).transform(lambda x: x.ewm(com=2).mean())
    d_val = k.groupby(df["code"]).transform(lambda x: x.ewm(com=2).mean())
    df["feat_KDJ_K"] = (k / 100).astype(f32)
    df["feat_KDJ_D"] = (d_val / 100).astype(f32)
    df["feat_KDJ_J"] = ((3 * k - 2 * d_val) / 100).astype(f32)

    # ---- OBV (归一化为比率) ----
    sign = np.sign(df["raw_pctChg"]).fillna(0)
    obv = (sign * df["raw_volume"]).groupby(df["code"]).cumsum()
    obv_ma20 = obv.groupby(df["code"]).transform(lambda x: x.rolling(20).mean())
    df["feat_OBV"] = (obv / (obv_ma20.abs() + 1e-10)).astype(f32)

    # ---- MFI (14 天) ----
    tp_mfi = (df["_high_adj"] + df["_low_adj"] + df["_close_adj"]) / 3
    mf = tp_mfi * df["raw_volume"]
    tp_diff = tp_mfi.groupby(df["code"]).diff()
    pos_mf = (mf * (tp_diff > 0)).groupby(df["code"]).transform(
        lambda x: x.rolling(14).sum()
    )
    neg_mf = (mf * (tp_diff < 0)).groupby(df["code"]).transform(
        lambda x: x.rolling(14).sum()
    )
    df["feat_MFI14"] = (pos_mf / (pos_mf + neg_mf + 1e-10)).astype(f32)

    features.extend([
        "feat_MACD_DIF", "feat_MACD_DEA", "feat_MACD_HIST",
        "feat_KDJ_K", "feat_KDJ_D", "feat_KDJ_J",
        "feat_OBV", "feat_MFI14",
    ])
    logger.info("[technical] fixed_params elapsed=%.1fs", time.time() - t_fixed)

    return df, features
