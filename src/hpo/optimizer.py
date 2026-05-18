"""
HPO 优化器主入口

API:
  run_hpo_pipeline(
      cfg=None,
      n_trials=50,
      objective_metric="sharpe_ratio",
      model_name=None,
      study_name=None,
      resume=False,
      output_dir=None,
      n_jobs=1,
      timeout=None,
  ) -> dict

功能:
  - 使用 Optuna TPE 采样器搜索最优超参数
  - 支持 MedianPruner 早停剪枝
  - 结果持久化到 SQLite + Parquet + YAML
  - 支持从配置读取 n_jobs/timeout 默认值
"""
import json
import logging
import os
from datetime import datetime
from typing import Any

import optuna
from optuna.pruners import MedianPruner
from optuna.samplers import TPESampler
import pandas as pd
import yaml

from src.config_loader import load_config
from src.hpo.objective import ObjectiveFunction, extract_objective_value
from src.hpo.storage import HPOStorage

logger = logging.getLogger(__name__)

# 默认 HPO 结果目录
DEFAULT_HPO_DIR = "data/results/hpo"


def run_hpo_pipeline(
    cfg: dict | None = None,
    n_trials: int = 50,
    objective_metric: str = "sharpe_ratio",
    model_name: str | None = None,
    study_name: str | None = None,
    resume: bool = False,
    output_dir: str | None = None,
    n_jobs: int = 1,
    timeout: float | None = None,
    verbose: bool = True,
) -> dict[str, Any]:
    """
    HPO 主入口函数

    Args:
        cfg: 配置字典 (None 则从 base_config.yaml 加载)
        n_trials: 优化试验次数
        objective_metric: 优化目标 (sharpe_ratio, ic_mean, icir, annual_return)
        model_name: 模型名称 (None 则使用 cfg 中的 active 模型)
        study_name: 研究名称 (用于持久化，None 则自动生成)
        resume: 是否恢复已有研究
        output_dir: 输出目录 (None 则使用 data/results/hpo)
        n_jobs: 并行数 (建议为 1，避免模型内部并行冲突)
        timeout: 超时时间 (秒)
        verbose: 是否打印详细信息

    Returns:
        优化结果字典:
          - best_params: 最优参数
          - best_value: 最优目标值
          - best_trial: 最优 trial 编号
          - n_trials: 实际试验次数
          - study_name: 研究名称
          - output_path: 结果保存路径
    """
    # 1. 加载配置
    if cfg is None:
        cfg = load_config()

    # 2. 确定 HPO 配置 (从配置读取默认值)
    hpo_cfg = cfg.get("hpo", {})
    n_trials = n_trials or hpo_cfg.get("n_trials", 50)
    output_dir = output_dir or hpo_cfg.get("output_dir", DEFAULT_HPO_DIR)
    n_jobs = n_jobs if n_jobs is not None else hpo_cfg.get("n_jobs", 1)
    timeout = timeout if timeout is not None else hpo_cfg.get("timeout", None)

    # 3. 确定模型
    if model_name is None:
        model_name = cfg.get("model", {}).get("active", "xgboost")

    # 4. 研究名称
    if study_name is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        study_name = f"hpo_{model_name}_{timestamp}"

    # 5. 创建输出目录
    os.makedirs(output_dir, exist_ok=True)

    # 6. 数据库路径
    db_path = os.path.join(output_dir, f"{study_name}.db")
    storage_url = f"sqlite:///{db_path}"

    # 7. 配置 Optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    sampler = TPESampler(
        seed=cfg.get("engine", {}).get("random_seed", 42),
        multivariate=True,  # 多变量联合优化
    )

    pruner = MedianPruner(
        n_startup_trials=5,      # 前 5 次不剪枝
        n_warmup_steps=0,        # 不预热
        interval_steps=1,        # 每步检查
    )

    # 8. 创建或恢复研究
    direction = "maximize"  # 所有目标都是越大越好

    if resume:
        try:
            study = optuna.load_study(
                study_name=study_name,
                storage=storage_url,
            )
            logger.info("[HPO] 恢复研究: %s (%d 已完成试验)", study_name, len(study.trials))
        except Exception as exc:
            logger.warning("[HPO] 无法恢复研究，创建新研究: %s", exc)
            study = optuna.create_study(
                study_name=study_name,
                storage=storage_url,
                sampler=sampler,
                pruner=pruner,
                direction=direction,
            )
    else:
        study = optuna.create_study(
            study_name=study_name,
            storage=storage_url,
            sampler=sampler,
            pruner=pruner,
            direction=direction,
        )

    # 9. 创建目标函数
    objective = ObjectiveFunction(
        base_cfg=cfg,
        model_name=model_name,
        objective_metric=objective_metric,
        output_dir=None,  # HPO 时不保存中间模型
        verbose=verbose,
    )

    # 10. 运行优化
    if verbose:
        print(f"\n[HPO] 开始超参数优化")
        print(f"   模型: {model_name}")
        print(f"   目标: {objective_metric} (maximize)")
        print(f"   试验次数: {n_trials}")
        print(f"   研究名称: {study_name}")
        print(f"   存储路径: {db_path}")
        print("-" * 50)

    study.optimize(
        objective,
        n_trials=n_trials,
        n_jobs=n_jobs,
        timeout=timeout,
        catch=(Exception,),
    )

    # 11. 保存结果
    result = _save_hpo_results(
        study=study,
        cfg=cfg,
        model_name=model_name,
        objective_metric=objective_metric,
        output_dir=output_dir,
        study_name=study_name,
    )

    if verbose:
        print("\n" + "=" * 50)
        print("[HPO] 优化完成")
        print(f"   最优目标值: {result['best_value']:.4f}")
        print(f"   最优参数:")
        for k, v in result["best_params"].items():
            print(f"     {k}: {v}")
        print(f"   结果保存至: {result['output_path']}")
        print("=" * 50)

    return result


def _save_hpo_results(
    study: optuna.Study,
    cfg: dict,
    model_name: str,
    objective_metric: str,
    output_dir: str,
    study_name: str,
) -> dict[str, Any]:
    """
    保存 HPO 结果 (使用 HPOStorage 类)

    保存内容:
      1. SQLite 数据库 (由 Optuna 自动维护)
      2. trials.parquet - 所有试验记录
      3. best_params.yaml - 最优参数
      4. summary.json - 摘要信息
    """
    best_trial = study.best_trial
    best_params = best_trial.params
    best_value = best_trial.value

    # 使用 HPOStorage 类保存结果
    storage = HPOStorage(output_dir)

    # 构建额外信息
    extra_info = {
        "model_config": {
            model_name: {k: _make_serializable(v) for k, v in best_params.items()}
        },
        "user_attrs": {
            k: _make_serializable(v)
            for k, v in best_trial.user_attrs.items()
        },
    }

    # 调用 HPOStorage.save_study 保存结果
    paths = storage.save_study(
        study=study,
        model_name=model_name,
        objective_metric=objective_metric,
        extra_info=extra_info,
    )

    # 为了兼容性，重命名文件 (移除时间戳后缀)
    import shutil
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 重命名 trials 文件
    old_trials_path = paths["trials_path"]
    new_trials_path = os.path.join(output_dir, f"{study_name}_trials.parquet")
    if old_trials_path != new_trials_path and os.path.exists(old_trials_path):
        shutil.move(old_trials_path, new_trials_path)

    # 重命名 best params 文件
    old_best_path = paths["best_params_path"]
    new_best_path = os.path.join(output_dir, f"{study_name}_best.yaml")
    if old_best_path != new_best_path and os.path.exists(old_best_path):
        shutil.move(old_best_path, new_best_path)

    # 重命名 summary 文件
    old_summary_path = paths["summary_path"]
    new_summary_path = os.path.join(output_dir, f"{study_name}_summary.json")
    if old_summary_path != new_summary_path and os.path.exists(old_summary_path):
        shutil.move(old_summary_path, new_summary_path)

    return {
        "best_params": best_params,
        "best_value": best_value,
        "best_trial": best_trial.number,
        "n_trials": len(study.trials),
        "study_name": study_name,
        "output_path": output_dir,
        "trials_path": new_trials_path,
        "best_params_path": new_best_path,
        "summary_path": new_summary_path,
    }


def _make_serializable(value: Any) -> Any:
    """确保值可以被 JSON/YAML 序列化"""
    import numpy as np

    if isinstance(value, (np.integer,)):
        return int(value)
    elif isinstance(value, (np.floating,)):
        return float(value)
    elif isinstance(value, np.ndarray):
        return value.tolist()
    elif isinstance(value, pd.Timestamp):
        return str(value)
    return value


def load_best_params(output_dir: str, study_name: str) -> dict:
    """
    加载已保存的最优参数

    Args:
        output_dir: 输出目录
        study_name: 研究名称

    Returns:
        最优参数字典
    """
    best_params_path = os.path.join(output_dir, f"{study_name}_best.yaml")
    if not os.path.exists(best_params_path):
        raise FileNotFoundError(f"未找到最优参数文件: {best_params_path}")

    with open(best_params_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def apply_best_params_to_config(cfg: dict, best_params: dict, model_name: str) -> dict:
    """
    将最优参数应用到配置

    Args:
        cfg: 原始配置
        best_params: 最优参数
        model_name: 模型名称

    Returns:
        更新后的配置
    """
    cfg = cfg.copy()
    cfg["model"] = cfg.get("model", {}).copy()
    cfg["model"]["active"] = model_name
    cfg["model"][model_name] = cfg["model"].get(model_name, {}).copy()

    # 只更新搜索空间中的参数，保留固定参数
    for key, value in best_params.items():
        cfg["model"][model_name][key] = value

    return cfg
