"""内置因子组：K线日内形态 (7 个因子，无需滚动窗口)"""
import pandas as pd
from src.registry import registry, FactorMeta


@registry.register_factor("kline", meta=FactorMeta(
    group="kline",
    input_cols=["raw_open", "raw_high", "raw_low", "raw_close"],
    output_cols=["feat_KMID", "feat_KLEN", "feat_KUP", "feat_KLOW",
                 "feat_KMID2", "feat_KUP2", "feat_KLOW2"],
    description="K线实体、上下影线等日内形态因子",
))
def kline_factors(
    df: pd.DataFrame, grouped, windows: list[int], f32: str
) -> tuple[pd.DataFrame, list[str]]:
    """K线实体、上下影线等日内形态因子"""
    features: list[str] = []

    df["feat_KMID"] = (
        (df["raw_close"] - df["raw_open"]) / (df["raw_open"] + 1e-10)
    ).astype(f32)
    df["feat_KLEN"] = (
        (df["raw_high"] - df["raw_low"]) / (df["raw_open"] + 1e-10)
    ).astype(f32)
    df["feat_KUP"] = (
        (df["raw_high"] - df[["raw_open", "raw_close"]].max(axis=1))
        / (df["raw_open"] + 1e-10)
    ).astype(f32)
    df["feat_KLOW"] = (
        (df[["raw_open", "raw_close"]].min(axis=1) - df["raw_low"])
        / (df["raw_open"] + 1e-10)
    ).astype(f32)
    df["feat_KMID2"] = (df["feat_KMID"] / (df["feat_KLEN"] + 1e-10)).astype(f32)
    df["feat_KUP2"] = (df["feat_KUP"] / (df["feat_KLEN"] + 1e-10)).astype(f32)
    df["feat_KLOW2"] = (df["feat_KLOW"] / (df["feat_KLEN"] + 1e-10)).astype(f32)

    features.extend([
        "feat_KMID", "feat_KLEN", "feat_KUP", "feat_KLOW",
        "feat_KMID2", "feat_KUP2", "feat_KLOW2",
    ])
    return df, features
