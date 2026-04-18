import pandas as pd

from src.label_gen import generate_labels


def test_generate_labels_pctchg_sum_matches_expected():
    cfg = {
        "label": {
            "name": "label_2d_ret",
            "horizon": 2,
            "method": "pctChg_sum",
        }
    }
    df = pd.DataFrame(
        {
            "code": ["A", "A", "A", "A", "B", "B", "B", "B"],
            "date": pd.date_range("2024-01-01", periods=4).tolist()
            + pd.date_range("2024-01-01", periods=4).tolist(),
            "raw_pctChg": [1.0, 2.0, 3.0, 4.0, 10.0, 20.0, 30.0, 40.0],
        }
    )

    result = generate_labels(df, cfg)

    expected = pd.Series([7.0, 70.0], name="label_2d_ret")
    pd.testing.assert_series_equal(
        result["label_2d_ret"].reset_index(drop=True),
        expected,
        check_dtype=False,
    )


def test_generate_labels_close_ratio_matches_expected():
    cfg = {
        "label": {
            "name": "label_1d_ret",
            "horizon": 1,
            "method": "close_ratio",
        }
    }
    df = pd.DataFrame(
        {
            "code": ["A", "A", "A"],
            "date": pd.date_range("2024-01-01", periods=3),
            "raw_close": [10.0, 11.0, 13.2],
        }
    )

    result = generate_labels(df, cfg)

    expected = pd.Series([0.1, 0.2], name="label_1d_ret")
    pd.testing.assert_series_equal(
        result["label_1d_ret"].reset_index(drop=True),
        expected,
        check_dtype=False,
    )
