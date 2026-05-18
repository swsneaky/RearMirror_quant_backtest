from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import traceback

# 确保从 tools/ 子目录也能找到仓库根目录的模块
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import pandas as pd

from pipeline import run_neutralize_pipeline
from src.config_loader import load_config
from src.data_layer import FeatureStore, LabelStore
from src.data_layer.db import get_asset


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run neutralize QA on a smaller smoke sample by default.")
    parser.add_argument("--start-date", default=None, help="Sample window start date, e.g. 2025-01-01")
    parser.add_argument("--end-date", default=None, help="Sample window end date, e.g. 2025-03-31")
    parser.add_argument("--days", type=int, default=60, help="Business-day window when --start-date is omitted")
    parser.add_argument("--max-codes", type=int, default=120, help="Max distinct codes in the smoke sample (0 = all)")
    parser.add_argument("--runs", type=int, default=2, help="How many repeated runs to execute")
    parser.add_argument(
        "--qa-dir",
        default=None,
        help="Sandbox output directory for QA artifacts and SQLite (default: qa/neutralize_smoke)",
    )
    parser.add_argument(
        "--full-sample",
        action="store_true",
        help="Use the full raw feature matrix instead of a smaller smoke sample",
    )
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be >= 1")
    if args.days < 1:
        parser.error("--days must be >= 1")
    if args.max_codes < 0:
        parser.error("--max-codes must be >= 0")
    return args


def build_qa_cfg(cfg: dict, qa_dir: str) -> dict:
    qa_cfg = copy.deepcopy(cfg)
    qa_dir = os.path.normpath(qa_dir)
    qa_features_dir = os.path.join(qa_dir, "features")
    qa_results_dir = os.path.join(qa_dir, "results")
    qa_logs_dir = os.path.join(qa_dir, "logs")
    qa_models_dir = os.path.join(qa_dir, "models")

    qa_cfg.setdefault("database", {})["path"] = os.path.join(qa_dir, "quant_qa.db")
    qa_cfg.setdefault("paths", {})["data_features"] = qa_features_dir
    qa_cfg["paths"]["data_results"] = qa_results_dir
    qa_cfg["paths"]["logs"] = qa_logs_dir
    qa_cfg["paths"]["models"] = qa_models_dir
    qa_cfg.setdefault("features", {})["output"] = os.path.join(qa_features_dir, "neutralized_smoke.parquet")

    analysis_cfg = qa_cfg.setdefault("analysis", {})
    analysis_cfg["ic_output"] = os.path.join(qa_results_dir, "ic_series.parquet")
    analysis_cfg["icir_output"] = os.path.join(qa_results_dir, "icir.parquet")
    analysis_cfg["ic_decay_output"] = os.path.join(qa_results_dir, "ic_decay.parquet")
    analysis_cfg["shap_output"] = os.path.join(qa_results_dir, "shap_importance.parquet")

    for path in [qa_dir, qa_features_dir, qa_results_dir, qa_logs_dir, qa_models_dir]:
        os.makedirs(path, exist_ok=True)
    return qa_cfg


def resolve_sample_window(raw_output: str, start_date: str | None, end_date: str | None, days: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    date_df = pd.read_parquet(raw_output, columns=["date"])
    date_df["date"] = pd.to_datetime(date_df["date"])
    min_date = pd.Timestamp(date_df["date"].min()).normalize()
    max_date = pd.Timestamp(date_df["date"].max()).normalize()

    sample_end = pd.Timestamp(end_date).normalize() if end_date else max_date
    if sample_end > max_date:
        sample_end = max_date
    if sample_end < min_date:
        raise ValueError(f"Requested end_date {sample_end.date()} is earlier than raw data min date {min_date.date()}")

    if start_date:
        sample_start = pd.Timestamp(start_date).normalize()
    else:
        sample_start = (sample_end - pd.offsets.BDay(days - 1)).normalize()
    if sample_start < min_date:
        sample_start = min_date
    if sample_start > sample_end:
        raise ValueError(f"Invalid sample window: {sample_start.date()} > {sample_end.date()}")
    return sample_start, sample_end


def load_sample_raw_df(raw_output: str, sample_start: pd.Timestamp, sample_end: pd.Timestamp, max_codes: int) -> tuple[pd.DataFrame, list[str]]:
    date_filters = [("date", ">=", sample_start), ("date", "<=", sample_end)]
    code_probe = pd.read_parquet(raw_output, columns=["code"], filters=date_filters)
    available_codes = sorted(code_probe["code"].dropna().unique().tolist())
    sample_codes = available_codes[:max_codes] if max_codes > 0 else available_codes

    filters = list(date_filters)
    if sample_codes:
        filters.append(("code", "in", sample_codes))

    try:
        raw_df = pd.read_parquet(raw_output, filters=filters)
    except Exception:
        raw_df = pd.read_parquet(raw_output)
        raw_df["date"] = pd.to_datetime(raw_df["date"])
        raw_df = raw_df[(raw_df["date"] >= sample_start) & (raw_df["date"] <= sample_end)]
        if sample_codes:
            raw_df = raw_df[raw_df["code"].isin(sample_codes)]

    raw_df["date"] = pd.to_datetime(raw_df["date"])
    raw_df = raw_df.sort_values(["code", "date"]).reset_index(drop=True)
    return raw_df, sample_codes


def collect_stats(df: pd.DataFrame, cfg: dict, asset_ids: dict) -> dict:
    label_name = cfg["label"]["name"]
    feature_cols = [col for col in df.columns if col.startswith("feat_")]
    feature_store = FeatureStore.from_config(cfg)
    label_store = LabelStore.from_config(cfg)
    feature_asset = get_asset(cfg, asset_ids.get("feature_set_id")) if asset_ids.get("feature_set_id") else None
    label_asset = get_asset(cfg, asset_ids.get("label_set_id")) if asset_ids.get("label_set_id") else None
    compat_path = cfg["features"]["output"]

    stats = {
        "rows": int(len(df)),
        "distinct_codes": int(df["code"].nunique()),
        "date_min": str(pd.to_datetime(df["date"]).min().date()),
        "date_max": str(pd.to_datetime(df["date"]).max().date()),
        "selected_feature_count": int(len(feature_cols)),
        "label_name": label_name,
        "pk_dup": int(df.duplicated(["date", "code"]).sum()),
        "compat_path": compat_path,
        "compat_exists": os.path.exists(compat_path),
        "compat_size": int(os.path.getsize(compat_path)) if os.path.exists(compat_path) else None,
        "feature_store_path": feature_store.store_path,
        "feature_store_exists": os.path.exists(feature_store.store_path),
        "label_store_path": label_store.store_path,
        "label_store_exists": os.path.exists(label_store.store_path),
        "feature_set_id": asset_ids.get("feature_set_id"),
        "label_set_id": asset_ids.get("label_set_id"),
        "feature_asset": {
            "table_name": feature_asset.get("table_name") if feature_asset else None,
            "row_count": int(feature_asset.get("row_count")) if feature_asset and feature_asset.get("row_count") is not None else None,
            "col_count": int(feature_asset.get("col_count")) if feature_asset and feature_asset.get("col_count") is not None else None,
        },
        "label_asset": {
            "table_name": label_asset.get("table_name") if label_asset else None,
            "row_count": int(label_asset.get("row_count")) if label_asset and label_asset.get("row_count") is not None else None,
            "col_count": int(label_asset.get("col_count")) if label_asset and label_asset.get("col_count") is not None else None,
        },
    }
    return stats


def main() -> int:
    args = parse_args()
    # 默认 QA 目录走统一路径解析器
    if args.qa_dir is None:
        from src.paths import project_paths
        args.qa_dir = project_paths.qa_session_dir("neutralize_smoke")
    cfg = load_config("configs/base_config.yaml")
    qa_cfg = build_qa_cfg(cfg, args.qa_dir)
    raw_output = cfg["features"]["raw_feature_output"]
    all_features = None
    raw_df = None

    print("[CONFIG] neutralize_output=", qa_cfg["features"]["output"])
    print("[CONFIG] raw_input=", raw_output)
    print("[CONFIG] label_name=", qa_cfg["label"]["name"])
    print("[CONFIG] qa_database=", qa_cfg["database"]["path"])

    if not args.full_sample:
        sample_start, sample_end = resolve_sample_window(raw_output, args.start_date, args.end_date, args.days)
        raw_df, sample_codes = load_sample_raw_df(raw_output, sample_start, sample_end, args.max_codes)
        if raw_df.empty:
            raise ValueError("Neutralize QA sample is empty; adjust --days/--start-date/--end-date/--max-codes")
        all_features = [col for col in raw_df.columns if col.startswith("feat_")]
        print(
            "[QA_SAMPLE]",
            json.dumps(
                {
                    "mode": "smoke",
                    "date_min": str(raw_df["date"].min().date()),
                    "date_max": str(raw_df["date"].max().date()),
                    "rows": int(len(raw_df)),
                    "distinct_codes": int(raw_df["code"].nunique()),
                    "max_codes": int(args.max_codes),
                    "selected_codes": int(len(sample_codes)),
                    "runs": int(args.runs),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
        )
    else:
        print("[QA_SAMPLE]", json.dumps({"mode": "full", "runs": int(args.runs)}, ensure_ascii=False, sort_keys=True))

    try:
        runs: list[dict] = []
        for idx in range(args.runs):
            df, asset_ids = run_neutralize_pipeline(
                qa_cfg,
                raw_df=raw_df.copy() if raw_df is not None else None,
                all_features=all_features,
            )
            run_stats = collect_stats(df, qa_cfg, asset_ids)
            runs.append(run_stats)
            print(f"[RUN{idx + 1}]", json.dumps(run_stats, ensure_ascii=False, sort_keys=True))

        if len(runs) >= 2:
            baseline = runs[0]
            latest = runs[-1]
            compare = {
                "rows_equal": baseline["rows"] == latest["rows"],
                "codes_equal": baseline["distinct_codes"] == latest["distinct_codes"],
                "date_min_equal": baseline["date_min"] == latest["date_min"],
                "date_max_equal": baseline["date_max"] == latest["date_max"],
                "selected_feature_count_equal": baseline["selected_feature_count"] == latest["selected_feature_count"],
                "label_name_equal": baseline["label_name"] == latest["label_name"],
                "pk_dup_equal": baseline["pk_dup"] == latest["pk_dup"],
                "feature_set_id_equal": baseline["feature_set_id"] == latest["feature_set_id"],
                "label_set_id_equal": baseline["label_set_id"] == latest["label_set_id"],
                "feature_table_equal": baseline["feature_asset"]["table_name"] == latest["feature_asset"]["table_name"],
                "label_table_equal": baseline["label_asset"]["table_name"] == latest["label_asset"]["table_name"],
                "compat_size_equal": baseline["compat_size"] == latest["compat_size"],
            }
            print("[COMPARE]", json.dumps(compare, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"[ERROR] {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())