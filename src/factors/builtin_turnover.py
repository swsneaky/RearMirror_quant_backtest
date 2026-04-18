"""
换手率因子 -- 需要 BaoStock turn 字段
==============================================
若 raw_turn 列不存在（旧缓存），自动跳过并返回空因子列表。

每窗口因子:
  TURN_MA, TURN_STD  -> 2 x len(windows)
固定:
  DTURN (换手率日变化)  -> 1
"""
import numpy as np
import pandas as pd

from src.registry import registry, FactorMeta


@registry.register_factor("turnover", meta=FactorMeta(
    group="turnover",
    input_cols=["raw_turn"],
    output_cols=["feat_DTURN", "feat_TURN_MA", "feat_TURN_STD"],
    description="换手率因子: DTURN/TURN_MA/TURN_STD (需 raw_turn)",
    windowed=True,
))
def turnover_factors(
    df: pd.DataFrame, grouped, windows: list[int], f32: str
) -> tuple[pd.DataFrame, list[str]]:
    """换手率系列因子 (需要 raw_turn 列)"""
    features: list[str] = []

    if "raw_turn" not in df.columns:
        print("    [WARN]  raw_turn 列缺失（旧缓存无换手率字段），跳过 turnover 因子组")
        return df, features

    # 换手率本身是百分比 (BaoStock)，转小数
    turn = df["raw_turn"] / 100

    # ---- DTURN: 换手率日变化 ----
    df["feat_DTURN"] = grouped["raw_turn"].transform(lambda x: x.diff()).astype(f32)
    features.append("feat_DTURN")

    for d in windows:
        df[f"feat_TURN_MA{d}"] = (
            turn.groupby(df["code"]).transform(lambda x: x.rolling(d).mean())
        ).astype(f32)
        df[f"feat_TURN_STD{d}"] = (
            turn.groupby(df["code"]).transform(lambda x: x.rolling(d).std())
        ).astype(f32)

        features.extend([f"feat_TURN_MA{d}", f"feat_TURN_STD{d}"])

    return df, features
