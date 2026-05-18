"""
Label generation utilities.
"""
from __future__ import annotations

import pandas as pd

from src.price_mode import apply_price_mode, get_price_mode


def compute_label_values(df: pd.DataFrame, method: str, horizon: int) -> pd.Series:
    """Compute label values from an adjusted panel (expects adj_close)."""
    if method == "pctChg_sum":
        if "adj_close" in df.columns and pd.to_numeric(df["adj_close"], errors="coerce").notna().any():
            daily_ret = df.groupby("code", sort=False)["adj_close"].pct_change()
        elif "raw_pctChg" in df.columns:
            daily_ret = pd.to_numeric(df["raw_pctChg"], errors="coerce")
        else:
            raise ValueError("pctChg_sum requires adj_close or raw_pctChg")
        shifted = daily_ret.groupby(df["code"], sort=False).shift(-horizon)
        return (
            shifted.groupby(df["code"], sort=False)
            .rolling(horizon)
            .sum()
            .reset_index(level=0, drop=True)
        )

    if method == "close_ratio":
        if "adj_close" in df.columns and pd.to_numeric(df["adj_close"], errors="coerce").notna().any():
            base_close = pd.to_numeric(df["adj_close"], errors="coerce")
        elif "raw_close" in df.columns:
            base_close = pd.to_numeric(df["raw_close"], errors="coerce")
        else:
            raise ValueError("close_ratio requires adj_close or raw_close")
        future_close = base_close.groupby(df["code"], sort=False).shift(-horizon)
        return future_close.div(base_close).sub(1.0)

    raise ValueError(f"Unsupported label method: {method}")


def generate_labels(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Generate prediction labels from config."""
    lbl_cfg = cfg["label"]
    name = lbl_cfg["name"]
    horizon = int(lbl_cfg["horizon"])
    method = str(lbl_cfg["method"])
    price_mode = get_price_mode(cfg)

    print(
        f"[TAG] generating labels ({name}, horizon={horizon}, price_mode={price_mode})...",
        flush=True,
    )

    adjusted = apply_price_mode(df, price_mode)
    label_values = compute_label_values(adjusted, method, horizon)

    df = pd.concat([df, label_values.rename(name)], axis=1, copy=False)
    before = len(df)
    df = df.dropna(subset=[name]).reset_index(drop=True)
    print(f"  drop rows without label: {before} -> {len(df)}", flush=True)
    return df
