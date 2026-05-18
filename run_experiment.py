"""
实验启动器 -- 一个 profile 文件 -> 隔离的实验目录 -> 完整回测 -> 指标落盘 + 台账登记

用法:
    python run_experiment.py configs/profiles/zz500_xgb_baseline.yaml
    python run_experiment.py configs/profiles/hs300_lgbm_depth6.yaml --steps feature,backtest
    python run_experiment.py configs/profiles/zz500_xgb_baseline.yaml --exp-id exp_20260330_01_zz500_xgb_baseline

命名规则:
    exp_{YYYYMMDD}_{NN}_{universe}_{model}_{variant}
    自动生成时会从 profile 推断 universe / model / variant
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

import yaml

from src.config_loader import load_experiment_config


# ====================================================
# 实验 ID 生成
# ====================================================
def _generate_exp_id(cfg: dict, experiments_dir: str) -> str:
    """从配置推断命名要素，自动递增当天序号"""
    today = datetime.now().strftime("%Y%m%d")
    universe = cfg.get("etl", {}).get("index_name", "unknown")
    model = cfg.get("model", {}).get("active", "unknown")

    # 当天已有多少个实验
    existing = [
        d for d in os.listdir(experiments_dir)
        if os.path.isdir(os.path.join(experiments_dir, d))
        and d.startswith(f"exp_{today}")
    ] if os.path.exists(experiments_dir) else []
    seq = len(existing) + 1

    return f"exp_{today}_{seq:02d}_{universe}_{model}"


# ====================================================
# 指标序列化 (去掉 Series/DataFrame，只保留标量)
# ====================================================
def _serialize_metrics(metrics: dict) -> dict:
    """将 evaluate() 输出转为 JSON 可序列化的 dict"""
    out = {}
    for k, v in metrics.items():
        if isinstance(v, (int, float, str, bool, type(None))):
            out[k] = v
        elif hasattr(v, "item"):  # numpy scalar
            out[k] = v.item()
    return out


# ====================================================
# 台账管理
# ====================================================
RUNS_CSV_HEADER = [
    "exp_id", "universe", "model", "top_k", "max_turnover",
    "label_horizon", "train_window",
    "ann_return", "ann_excess_return", "sharpe_ratio",
    "information_ratio", "max_drawdown", "excess_max_drawdown",
    "avg_turnover", "avg_cost_per_period",
    "run_date", "profile", "notes",
]


def _append_runs_csv(
    csv_path: str,
    exp_id: str,
    cfg: dict,
    metrics: dict,
    profile_path: str,
    notes: str = "",
) -> None:
    """向实验台账追加一行"""
    file_exists = os.path.exists(csv_path)
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RUNS_CSV_HEADER)
        if not file_exists:
            writer.writeheader()
        row = {
            "exp_id": exp_id,
            "universe": cfg.get("etl", {}).get("index_name", ""),
            "model": cfg.get("model", {}).get("active", ""),
            "top_k": cfg.get("backtest", {}).get("top_k", ""),
            "max_turnover": cfg.get("backtest", {}).get("max_turnover", ""),
            "label_horizon": cfg.get("label", {}).get("horizon", ""),
            "train_window": cfg.get("backtest", {}).get("train_window", ""),
            "ann_return": f"{metrics.get('ann_return', 0):.4f}",
            "ann_excess_return": f"{metrics.get('ann_excess_return', 0):.4f}",
            "sharpe_ratio": f"{metrics.get('sharpe_ratio', 0):.4f}",
            "information_ratio": f"{metrics.get('information_ratio', 0):.4f}",
            "max_drawdown": f"{metrics.get('max_drawdown', 0):.4f}",
            "excess_max_drawdown": f"{metrics.get('excess_max_drawdown', 0):.4f}",
            "avg_turnover": f"{metrics.get('avg_turnover', 0):.4f}",
            "avg_cost_per_period": f"{metrics.get('avg_cost_per_period', 0):.6f}",
            "run_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "profile": profile_path,
            "notes": notes,
        }
        writer.writerow(row)


# ====================================================
# 主流程
# ====================================================
def run_experiment(
    profile_path: str,
    steps: list[str] | None = None,
    exp_id: str | None = None,
    notes: str = "",
) -> dict:
    """
    实验全流程:
      1. 合并 base + profile -> 完整配置
      2. 创建隔离的实验目录
      3. 快照配置到 experiments/{exp_id}/config.yaml
      4. 执行流水线
      5. 保存 metrics.json + 追加 runs.csv
    """
    if steps is None:
        steps = ["feature", "backtest"]

    experiments_dir = "experiments"
    os.makedirs(experiments_dir, exist_ok=True)

    # 1. 先用临时 merge 拿到配置来生成 exp_id
    from src.config_loader import load_experiment_config as _lec
    tmp_cfg = _lec(profile_path)
    if exp_id is None:
        exp_id = _generate_exp_id(tmp_cfg, experiments_dir)

    exp_dir = os.path.join(experiments_dir, exp_id)
    os.makedirs(exp_dir, exist_ok=True)

    # 2. 正式合并，注入实验目录
    cfg = _lec(profile_path, exp_dir=exp_dir)

    # 3. 快照完整配置
    config_snapshot = os.path.join(exp_dir, "config.yaml")
    with open(config_snapshot, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    print(f"[EXP] 实验 [{exp_id}]")
    print(f"   配置快照: {config_snapshot}")
    print(f"   输出目录: {exp_dir}")
    print(f"   步骤: {steps}")
    print()

    # 4. 按步骤执行
    from pipeline import (
        run_raw_feature_pipeline, run_neutralize_pipeline,
        run_feature_pipeline, run_backtest_pipeline, run_factor_analysis,
    )
    from src.data_hub import run_downloader, merge_and_clean

    metrics = {}

    if "download" in steps:
        run_downloader(cfg)

    if "etl" in steps:
        merge_and_clean(cfg)

    # 兼容旧步骤名 "feature" = raw_feature + neutralize
    if "feature" in steps:
        run_feature_pipeline(cfg)
    else:
        if "raw_feature" in steps:
            raw_df, feats, gfm = run_raw_feature_pipeline(cfg)
        else:
            raw_df, feats, gfm = None, None, None
        if "neutralize" in steps:
            run_neutralize_pipeline(cfg, raw_df, feats, gfm)

    if "backtest" in steps:
        results_df, metrics = run_backtest_pipeline(cfg)

        # 保存 metrics.json (标量)
        results_dir = os.path.join(exp_dir, "results")
        os.makedirs(results_dir, exist_ok=True)
        metrics_json = os.path.join(results_dir, "metrics.json")
        with open(metrics_json, "w", encoding="utf-8") as f:
            json.dump(_serialize_metrics(metrics), f, indent=2, ensure_ascii=False)
        print(f"\n[SAVE] 指标已保存: {metrics_json}")

        # 保存原始回测结果
        results_parquet = os.path.join(results_dir, "backtest_results.parquet")
        results_df.to_parquet(results_parquet, index=False, engine="pyarrow")

    if "factor_analysis" in steps:
        run_factor_analysis(cfg)

    # 6. 追加台账
    runs_csv = os.path.join(experiments_dir, "runs.csv")
    _append_runs_csv(runs_csv, exp_id, cfg, _serialize_metrics(metrics), profile_path, notes)
    print(f"[LOG] 台账已更新: {runs_csv}")

    return {"exp_id": exp_id, "exp_dir": exp_dir, "metrics": metrics, "cfg": cfg}


# ====================================================
# CLI
# ====================================================
def main():
    parser = argparse.ArgumentParser(description="RearMirror 实验启动器")
    parser.add_argument("profile", help="实验 profile YAML 路径 (只需写覆盖项)")
    parser.add_argument(
        "--steps", default="raw_feature,neutralize,backtest",
        help="执行步骤，逗号分隔 (download,etl,raw_feature,neutralize,feature,backtest,factor_analysis)",
    )
    parser.add_argument("--exp-id", default=None, help="手动指定实验 ID")
    parser.add_argument("--notes", default="", help="备注信息")
    args = parser.parse_args()

    steps = [s.strip() for s in args.steps.split(",")]
    run_experiment(args.profile, steps=steps, exp_id=args.exp_id, notes=args.notes)


if __name__ == "__main__":
    main()
