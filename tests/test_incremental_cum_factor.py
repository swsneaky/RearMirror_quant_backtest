import math

import pandas as pd

from src.data_hub.baostock_client import _recompute_cum_factor
from src.data_hub.etl_process import _ensure_cum_factor, _ingest_to_db
from src.data_layer.db import close_connection, get_connection


def test_recompute_cum_factor_after_incremental_merge():
    old_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-04-07", "2026-04-08"]),
            "code": ["sh.600000", "sh.600000"],
            "pctChg": [1.0, 2.0],
            "cum_factor": [1.01, 1.0302],
        }
    )
    new_df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-04-09", "2026-04-10"]),
            "code": ["sh.600000", "sh.600000"],
            "pctChg": [-1.0, 0.5],
            "cum_factor": [0.99, 0.99495],
        }
    )

    merged = pd.concat([old_df, new_df], ignore_index=True)
    got = _recompute_cum_factor(merged)

    expected = [1.01, 1.0302, 1.019898, 1.02499749]
    assert got["date"].is_monotonic_increasing
    for actual, want in zip(got["cum_factor"], expected):
        assert math.isclose(actual, want, rel_tol=1e-9)


def test_ensure_cum_factor_rebuilds_from_canonical_raw_pctchg():
    raw_df = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2026-04-08", "2026-04-09", "2026-04-08", "2026-04-09"]
            ),
            "code": ["sh.600001", "sh.600001", "sh.600002", "sh.600002"],
            "raw_pctChg": [0.01, 0.02, None, -0.03],
            "cum_factor": [None, None, 99.0, None],
        }
    )

    got = _ensure_cum_factor(raw_df)

    by_key = {
        (row.code, row.date.strftime("%Y-%m-%d")): row.cum_factor
        for row in got.itertuples(index=False)
    }
    assert math.isclose(by_key[("sh.600001", "2026-04-08")], 1.01, rel_tol=1e-9)
    assert math.isclose(by_key[("sh.600001", "2026-04-09")], 1.0302, rel_tol=1e-9)
    assert math.isclose(by_key[("sh.600002", "2026-04-08")], 1.0, rel_tol=1e-9)
    assert math.isclose(by_key[("sh.600002", "2026-04-09")], 0.97, rel_tol=1e-9)


def test_incremental_ingest_upserts_existing_null_cum_factor(tmp_path):
    cfg = {
        "database": {"path": str(tmp_path / "quant.db")},
        "etl": {"industry_map": str(tmp_path / "missing_industry.parquet")},
    }

    seed = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-04-09"]),
            "code": ["sh.600000"],
            "raw_close": [10.0],
            "raw_pctChg": [0.01],
            "cum_factor": [None],
            "isST": [0],
            "tradestatus": [1],
            "industry": ["Bank"],
        }
    )
    fixed = seed.copy()
    fixed["cum_factor"] = [1.01]

    try:
        _ingest_to_db(seed, cfg, update_mode="full")
        _ingest_to_db(fixed, cfg, update_mode="incremental")

        con = get_connection(cfg)
        row = con.execute(
            "SELECT COUNT(*), MAX(cum_factor) FROM daily_bar WHERE code = ?",
            ["sh.600000"],
        ).fetchone()
        assert row == (1, 1.01)
    finally:
        close_connection(cfg)
