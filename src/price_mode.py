"""
Price mode utilities.

Canonical storage keeps raw OHLC plus adjustment factors. Downstream
feature/label/backtest code should consume a unified adjusted view.
"""
from __future__ import annotations

import pandas as pd

_VALID_PRICE_MODES = {"raw", "forward", "backward"}


def get_price_mode(cfg: dict) -> str:
    """Read configured price mode with a backward-compatible default."""
    mode = str(cfg.get("price", {}).get("mode", "raw")).strip().lower()
    if mode not in _VALID_PRICE_MODES:
        raise ValueError(f"Unknown price.mode: {mode!r}, expected one of {_VALID_PRICE_MODES}")
    return mode


def get_price_factor(frame: pd.DataFrame, mode: str) -> pd.Series:
    """Return per-row multiplicative factor for the selected mode."""
    mode = str(mode).strip().lower()
    if mode == "raw":
        return pd.Series(1.0, index=frame.index, dtype="float64")
    if mode == "forward":
        if "fwd_factor" not in frame.columns:
            return pd.Series(1.0, index=frame.index, dtype="float64")
        return pd.to_numeric(frame["fwd_factor"], errors="coerce").fillna(1.0)
    if mode == "backward":
        if "bwd_factor" not in frame.columns:
            return pd.Series(1.0, index=frame.index, dtype="float64")
        return pd.to_numeric(frame["bwd_factor"], errors="coerce").fillna(1.0)
    raise ValueError(f"Unknown price mode: {mode!r}")


def apply_price_mode(frame: pd.DataFrame, mode: str) -> pd.DataFrame:
    """
    Build adjusted OHLC projection columns from raw price + selected factor.

    Added columns:
      - adj_open, adj_high, adj_low, adj_close, adj_factor
    """
    out = frame.copy()
    factor = get_price_factor(out, mode)
    close = (
        pd.to_numeric(out.get("raw_close"), errors="coerce")
        if "raw_close" in out.columns
        else pd.Series(float("nan"), index=out.index, dtype="float64")
    )
    open_ = pd.to_numeric(out.get("raw_open", close), errors="coerce")
    high = pd.to_numeric(out.get("raw_high", close), errors="coerce")
    low = pd.to_numeric(out.get("raw_low", close), errors="coerce")
    out["adj_factor"] = factor
    out["adj_open"] = open_ * factor
    out["adj_high"] = high * factor
    out["adj_low"] = low * factor
    out["adj_close"] = close * factor
    return out
