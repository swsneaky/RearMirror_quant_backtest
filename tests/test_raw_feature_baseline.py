import time
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd
import pandas.testing as pdt

from pipeline import run_raw_feature_pipeline
from src.data_layer.db import close_connection, get_connection, ingest_dataframe
from src.feature_engine import build_alpha158


def _get_rss_mb() -> float:
    try:
        import psutil

        return psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:
        pass
    try:
        import ctypes

        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        if ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(),
            ctypes.byref(counters),
            counters.cb,
        ):
            return counters.WorkingSetSize / (1024 * 1024)
    except Exception:
        pass
    return -1.0


def _make_synthetic_panel(n_dates: int) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    dates = pd.date_range("2021-01-01", periods=n_dates, freq="B")
    frames = []
    for i, code in enumerate(["000001.SZ", "000002.SZ", "000003.SZ"]):
        base = 10 + i
        close = base + np.cumsum(rng.normal(0.05, 0.2, size=n_dates))
        open_ = close * (1 + rng.normal(0.0, 0.01, size=n_dates))
        high = np.maximum(open_, close) * (1 + rng.uniform(0.0, 0.02, size=n_dates))
        low = np.minimum(open_, close) * (1 - rng.uniform(0.0, 0.02, size=n_dates))
        volume = rng.integers(1_000_000, 3_000_000, size=n_dates).astype(float)
        amount = volume * close
        pct = pd.Series(close).pct_change().fillna(0.0).to_numpy() * 100.0

        df = pd.DataFrame(
            {
                "date": dates,
                "code": code,
                "raw_open": open_,
                "raw_high": high,
                "raw_low": low,
                "raw_close": close,
                "raw_volume": volume,
                "raw_amount": amount,
                "raw_pctChg": pct,
                "cum_factor": 1.0,
                "isST": 0,
                "tradestatus": 1,
            }
        )
        frames.append(df)

    panel = pd.concat(frames, ignore_index=True)

    # 注入极端情况: NaN、停牌、非单调时间戳
    panel.loc[(panel["code"] == "000001.SZ") & (panel["date"] == dates[2]), "raw_close"] = np.nan
    panel.loc[(panel["code"] == "000002.SZ") & (panel["date"] == dates[4]), "raw_volume"] = np.nan
    panel.loc[(panel["code"] == "000003.SZ") & (panel["date"] == dates[6]), "tradestatus"] = 0

    # 打乱顺序构造非单调输入
    return panel.sample(frac=1.0, random_state=7).reset_index(drop=True)


class _FakeCanonicalStore:
    def __init__(self, daily_df: pd.DataFrame):
        self._daily_df = daily_df

    def load_daily(self) -> pd.DataFrame:
        return self._daily_df.copy()

    def load_industry(self) -> pd.DataFrame:
        codes = sorted(self._daily_df["code"].unique().tolist())
        return pd.DataFrame({"code": codes, "industry": ["Bank", "Tech", "Energy"][: len(codes)]})


def _base_cfg(tmp_path: Path) -> dict:
    return {
        "database": {"path": str(tmp_path / "quant.db")},
        "paths": {"data_features": str(tmp_path / "features")},
        "etl": {
            "raw_output": str(tmp_path / "raw_dummy.parquet"),
            "industry_map": str(tmp_path / "industry_dummy.parquet"),
        },
        "features": {
            "active_factors": ["kline", "rolling"],
            "excluded_features": [],
            "raw_feature_output": str(tmp_path / "features" / "raw_feature.parquet"),
            "output": str(tmp_path / "features" / "neutralized.parquet"),
            "windows": [3, 5],
            "min_listing_days": 0,
            "kline_features": ["KMID", "KLEN", "KUP", "KLOW", "KMID2", "KUP2", "KLOW2"],
            "rolling_features": [
                "ROC",
                "MA",
                "STD",
                "EMA",
                "MAX",
                "MIN",
                "RSV",
                "IMAX",
                "IMIN",
                "RANK",
                "VMA",
                "VSTD",
                "WVMA",
                "CORR",
                "BETA",
                "RSQR",
                "RESI",
            ],
            "rolling_ext_features": [],
            "technical_features": {"per_window": [], "fixed": []},
            "turnover_features": {"per_window": [], "fixed": []},
            "valuation_features": {"metrics": [], "per_metric_per_window": [], "per_metric_fixed": []},
        },
        "engine": {"float_dtype": "float32"},
        "cross_section": {},
        "label": {"name": "label_5d_ret", "horizon": 5},
    }


def _seed_daily_bar(cfg: dict, daily: pd.DataFrame) -> None:
    db_daily = daily.copy()
    db_daily["date"] = pd.to_datetime(db_daily["date"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    ingest_dataframe(cfg, "daily_bar", db_daily, mode="replace")


def test_raw_feature_handles_nan_suspend_and_unsorted_input(monkeypatch, tmp_path):
    cfg = _base_cfg(tmp_path)
    daily = _make_synthetic_panel(15)

    from src.data_layer import canonical

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(canonical.CanonicalStore, "from_config", lambda _cfg: _FakeCanonicalStore(daily))

    t0 = time.perf_counter()
    rss0 = _get_rss_mb()
    with redirect_stdout(StringIO()):
        raw_df, all_features, _ = run_raw_feature_pipeline(cfg)
    elapsed = time.perf_counter() - t0
    rss1 = _get_rss_mb()

    assert not raw_df.empty
    assert len(all_features) > 0
    assert {"date", "code", "industry", "tradestatus"}.issubset(raw_df.columns)
    assert raw_df.sort_values(["code", "date"]).reset_index(drop=True).equals(raw_df.reset_index(drop=True))

    # NaN 和停牌不应导致流程崩溃; 至少应保留部分样本
    assert raw_df["tradestatus"].isin([0, 1]).all()
    assert raw_df[all_features].shape[0] > 0

    print(
        f"[baseline-metric] robustness elapsed={elapsed:.3f}s rss_before={rss0:.1f}MB "
        f"rss_after={rss1:.1f}MB delta={rss1 - rss0:.1f}MB rows={len(raw_df)} feats={len(all_features)}"
    )
    close_connection(cfg)


def test_raw_feature_incremental_equals_full_recompute(monkeypatch, tmp_path):
    cfg = _base_cfg(tmp_path)
    full_daily = _make_synthetic_panel(20)

    from src.data_layer import canonical

    monkeypatch.chdir(tmp_path)

    # 第一次: 仅历史窗口
    hist_dates = sorted(full_daily["date"].unique())[:12]
    hist_daily = full_daily[full_daily["date"].isin(hist_dates)].copy()
    monkeypatch.setattr(canonical.CanonicalStore, "from_config", lambda _cfg: _FakeCanonicalStore(hist_daily))
    with redirect_stdout(StringIO()):
        run_raw_feature_pipeline(cfg)

    raw_path = Path(cfg["features"]["raw_feature_output"])
    assert raw_path.exists()
    raw_path.unlink()
    assert not raw_path.exists()

    _seed_daily_bar(cfg, full_daily)
    con = get_connection(cfg)
    before = con.execute("SELECT COUNT(*), MAX(DATE(date)) FROM feature_wide").fetchone()

    # 第二次: 切换到全量源，触发增量追加
    monkeypatch.setattr(canonical.CanonicalStore, "from_config", lambda _cfg: _FakeCanonicalStore(full_daily))
    t_inc0 = time.perf_counter()
    rss_inc0 = _get_rss_mb()
    with redirect_stdout(StringIO()):
        inc_df, inc_features, _ = run_raw_feature_pipeline(cfg)
    t_inc = time.perf_counter() - t_inc0
    rss_inc1 = _get_rss_mb()

    # 基准: 直接全量重算
    t_full0 = time.perf_counter()
    rss_full0 = _get_rss_mb()
    with redirect_stdout(StringIO()):
        full_factor_df, full_features, _ = build_alpha158(
            cfg,
            factor_groups=cfg["features"]["active_factors"],
            input_df=full_daily,
        )
    t_full = time.perf_counter() - t_full0
    rss_full1 = _get_rss_mb()

    meta_cols = [
        c
        for c in ["date", "code", "industry", "isST", "tradestatus", "raw_pctChg", "raw_amount"]
        if c in full_factor_df.columns
    ]
    expected_cols = meta_cols + full_features
    expected_df = full_factor_df[[c for c in expected_cols if c in full_factor_df.columns]].copy()
    expected_df = expected_df.sort_values(["code", "date"]).reset_index(drop=True)

    got_df = inc_df.sort_values(["code", "date"]).reset_index(drop=True)
    after = con.execute("SELECT COUNT(*), MAX(DATE(date)) FROM feature_wide").fetchone()

    assert set(full_features) == set(inc_features)
    pdt.assert_frame_equal(got_df[expected_df.columns], expected_df, check_dtype=False, check_like=False)
    assert raw_path.exists()
    assert before[1] < after[1]
    assert after[0] - before[0] == len(inc_df) - before[0]

    print(
        f"[baseline-metric] incremental elapsed={t_inc:.3f}s rss_delta={rss_inc1 - rss_inc0:.1f}MB; "
        f"full elapsed={t_full:.3f}s rss_delta={rss_full1 - rss_full0:.1f}MB"
    )
    close_connection(cfg)
