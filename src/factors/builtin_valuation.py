"""
估值因子 -- 需要 BaoStock peTTM / pbMRQ / psTTM / pcfNcfTTM
==============================================================
若对应列不存在（旧缓存），自动跳过。

对每个估值指标取 log 并计算滚动 Z-Score（截面排序更稳定）。

每指标因子:
  log_XXX, XXX_MA{d}, XXX_RANK{d}

BaoStock 返回的估值指标本身已是 TTM/MRQ 口径。
"""
import numpy as np
import pandas as pd

from src.registry import registry, FactorMeta

# 需要下载的估值字段映射
_VALUATION_COLS = {
    "raw_peTTM":      "PE",
    "raw_pbMRQ":      "PB",
    "raw_psTTM":      "PS",
    "raw_pcfNcfTTM":  "PCF",
}


def _rolling_pct_rank(y):
    """窗口内末尾元素的百分位排名 (纯 numpy, 替代 pd.Series.rank)"""
    return np.searchsorted(np.sort(y), y[-1], side="right") / len(y)


@registry.register_factor("valuation", meta=FactorMeta(
    group="valuation",
    input_cols=["raw_peTTM", "raw_pbMRQ", "raw_psTTM", "raw_pcfNcfTTM"],
    output_cols=["feat_LOG_PE", "feat_LOG_PB", "feat_LOG_PS", "feat_LOG_PCF",
                 "feat_PE_MA", "feat_PE_RANK", "feat_PB_MA", "feat_PB_RANK",
                 "feat_PS_MA", "feat_PS_RANK", "feat_PCF_MA", "feat_PCF_RANK"],
    description="估值因子: PE/PB/PS/PCF 的 log + 滚动均值 + 滚动排名",
    windowed=True,
))
def valuation_factors(
    df: pd.DataFrame, grouped, windows: list[int], f32: str
) -> tuple[pd.DataFrame, list[str]]:
    """估值因子：PE / PB / PS / PCF 的 log + 滚动均值 + 滚动排名"""
    features: list[str] = []

    available = {raw: tag for raw, tag in _VALUATION_COLS.items() if raw in df.columns}
    if not available:
        print("    [WARN] 估值列缺失（旧缓存无 peTTM 等字段），跳过 valuation 因子组")
        return df, features

    for raw_col, tag in available.items():
        # log 变换 (PE/PB 只在正值域有意义)
        log_col = f"feat_LOG_{tag}"
        df[log_col] = np.log(df[raw_col].clip(lower=0.01)).astype(f32)
        features.append(log_col)

        for d in windows:
            # 滚动均值偏离
            ma_col = f"feat_{tag}_MA{d}"
            ma = df[log_col].groupby(df["code"]).transform(
                lambda x: x.rolling(d).mean()
            )
            df[ma_col] = (df[log_col] - ma).astype(f32)
            features.append(ma_col)

            # 滚动分位排名 (纯 numpy, 替代 pd.Series.rank 开销)
            rank_col = f"feat_{tag}_RANK{d}"
            df[rank_col] = df[log_col].groupby(df["code"]).transform(
                lambda x: x.rolling(d).apply(_rolling_pct_rank, raw=True)
            ).astype(f32)
            features.append(rank_col)

    return df, features
