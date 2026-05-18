from __future__ import annotations

import argparse
import json
import os
import sys
import traceback

# 确保从 tools/ 子目录也能找到仓库根目录的模块
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from tools.qa_neutralize_run import collect_stats
from pipeline import run_neutralize_pipeline
from src.config_loader import load_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run full neutralize validation on formal paths.")
    parser.add_argument("--runs", type=int, default=2, help="How many repeated runs to execute")
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be >= 1")
    return args


def main() -> int:
    args = parse_args()
    cfg = load_config("configs/base_config.yaml")

    print("[CONFIG] neutralize_output=", cfg["features"]["output"])
    print("[CONFIG] raw_input=", cfg["features"]["raw_feature_output"])
    print("[CONFIG] label_name=", cfg["label"]["name"])
    print("[CONFIG] database=", cfg["database"]["path"])

    try:
        runs: list[dict] = []
        for idx in range(args.runs):
            df, asset_ids = run_neutralize_pipeline(cfg)
            run_stats = collect_stats(df, cfg, asset_ids)
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