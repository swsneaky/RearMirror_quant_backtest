import math

import pandas as pd

from src.label_gen import generate_labels
from src.price_mode import apply_price_mode, get_price_mode


def test_apply_price_mode_forward_and_backward():
    df = pd.DataFrame(
        {
            "raw_open": [10.0],
            "raw_high": [11.0],
            "raw_low": [9.0],
            "raw_close": [10.0],
            "fwd_factor": [0.5],
            "bwd_factor": [2.0],
        }
    )

    fwd = apply_price_mode(df, "forward")
    bwd = apply_price_mode(df, "backward")

    assert math.isclose(float(fwd.loc[0, "adj_close"]), 5.0, rel_tol=1e-9)
    assert math.isclose(float(bwd.loc[0, "adj_close"]), 20.0, rel_tol=1e-9)


def test_get_price_mode_default_and_validation():
    assert get_price_mode({}) == "raw"
    assert get_price_mode({"price": {"mode": "forward"}}) == "forward"

    try:
        get_price_mode({"price": {"mode": "bad_mode"}})
    except ValueError:
        pass
    else:
        raise AssertionError("invalid price mode should raise ValueError")


def test_generate_labels_close_ratio_honors_forward_mode():
    cfg = {
        "price": {"mode": "forward"},
        "label": {
            "name": "label_1d_ret",
            "horizon": 1,
            "method": "close_ratio",
        },
    }
    df = pd.DataFrame(
        {
            "code": ["A", "A"],
            "date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "raw_close": [10.0, 10.0],
            "fwd_factor": [1.0, 0.5],
        }
    )

    result = generate_labels(df, cfg)
    got = float(result["label_1d_ret"].iloc[0])
    assert math.isclose(got, -0.5, rel_tol=1e-9)
