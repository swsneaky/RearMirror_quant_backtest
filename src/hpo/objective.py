"""
目标函数定义

调用 run_backtest_pipeline 进行评估，返回指定的优化目标

支持优化目标:
  - sharpe_ratio: 夏普比率 (越大越好)
  - ic_mean: 平均 IC (越大越好)
  - icir: IC 信息比率 (越大越好)
  - annual_return: 年化收益 (越大越好)
"""
import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_ic_from_predictions(results_df: pd.DataFrame, label_name: str) -> pd.Series:
    """
    从预测结果计算 IC 序列

    IC = rank_corr(pred_score, label)

    Args:
        results_df: 包含 pred_score 和 label 的预测结果
        label_name: 标签列名

    Returns:
        IC 序列 (按日期)
    """
    if results_df.empty:
        return pd.Series(dtype=float)

    ic_list = []
    dates = results_df["date"].unique()

    for date in dates:
        day_df = results_df[results_df["date"] == date]
        if len(day_df) < 5:  # 样本太少跳过
            continue

        pred = day_df["pred_score"]
        label = day_df[label_name]

        # Spearman 秩相关
        pred_rank = pred.rank()
        label_rank = label.rank()
        ic = pred_rank.corr(label_rank)
        ic_list.append({"date": date, "ic": ic})

    if not ic_list:
        return pd.Series(dtype=float)

    ic_df = pd.DataFrame(ic_list).set_index("date")
    return ic_df["ic"]


def extract_objective_value(
    metrics: dict,
    results_df: pd.DataFrame,
    objective_metric: str,
    label_name: str,
) -> float:
    """
    从回测结果中提取目标值

    Args:
        metrics: 回测指标字典
        results_df: 预测结果 DataFrame
        objective_metric: 目标指标名称
        label_name: 标签列名

    Returns:
        目标值 (越大越好)
    """
    if objective_metric == "sharpe_ratio":
        return metrics.get("sharpe_ratio", 0.0)

    elif objective_metric == "annual_return":
        return metrics.get("ann_return", 0.0)

    elif objective_metric == "ic_mean":
        ic_series = compute_ic_from_predictions(results_df, label_name)
        if ic_series.empty:
            return 0.0
        return ic_series.mean()

    elif objective_metric == "icir":
        ic_series = compute_ic_from_predictions(results_df, label_name)
        if ic_series.empty or len(ic_series) < 2:
            return 0.0
        ic_mean = ic_series.mean()
        ic_std = ic_series.std()
        if ic_std == 0:
            return 0.0
        # ICIR = IC_mean / IC_std * sqrt(252/step)
        # 简化版: ICIR = IC_mean / IC_std
        return ic_mean / ic_std if ic_std > 0 else 0.0

    else:
        raise ValueError(
            f"不支持的优化目标: {objective_metric}，"
            f"支持: sharpe_ratio, ic_mean, icir, annual_return"
        )


class ObjectiveFunction:
    """
    Optuna 目标函数封装

    用法:
        objective = ObjectiveFunction(cfg, model_name, objective_metric)
        study.optimize(objective, n_trials=100)
    """

    def __init__(
        self,
        base_cfg: dict,
        model_name: str,
        objective_metric: str,
        output_dir: str | None = None,
        feature_set_id: str | None = None,
        label_set_id: str | None = None,
        verbose: bool = False,
    ):
        """
        初始化目标函数

        Args:
            base_cfg: 基础配置
            model_name: 模型名称
            objective_metric: 优化目标
            output_dir: 输出目录 (可选)
            feature_set_id: 特征集 ID
            label_set_id: 标签集 ID
            verbose: 是否打印详细信息
        """
        self.base_cfg = base_cfg
        self.model_name = model_name
        self.objective_metric = objective_metric
        self.output_dir = output_dir
        self.feature_set_id = feature_set_id
        self.label_set_id = label_set_id
        self.verbose = verbose
        self.label_name = base_cfg.get("label", {}).get("name", "label_5d_ret")

    def __call__(self, trial) -> float:
        """
        执行单次优化试验

        Returns:
            目标值 (越大越好)
        """
        from src.hpo.search_space import get_search_space, merge_params
        from pipeline import run_backtest_pipeline

        # 1. 生成参数配置
        cfg = merge_params(self.base_cfg, self.model_name, trial)

        # 2. 运行回测
        try:
            # 设置静默模式
            if not self.verbose:
                import logging
                logging.getLogger("pipeline").setLevel(logging.WARNING)

            results_df, metrics = run_backtest_pipeline(
                cfg=cfg,
                output_dir=self.output_dir,
                feature_set_id=self.feature_set_id,
                label_set_id=self.label_set_id,
            )

            # 3. 提取目标值
            value = extract_objective_value(
                metrics, results_df, self.objective_metric, self.label_name
            )

            # 4. 记录试验信息
            trial.set_user_attr("model_name", self.model_name)
            trial.set_user_attr("objective_metric", self.objective_metric)
            trial.set_user_attr("ann_return", metrics.get("ann_return", 0.0))
            trial.set_user_attr("sharpe_ratio", metrics.get("sharpe_ratio", 0.0))
            trial.set_user_attr("max_drawdown", metrics.get("max_drawdown", 0.0))

            if self.verbose:
                print(f"[Trial {trial.number}] {self.objective_metric}={value:.4f}")

            return value

        except Exception as exc:
            logger.warning("Trial %d 失败: %s", trial.number, exc)
            # 返回极差值
            return -999.0


def create_objective(
    base_cfg: dict,
    model_name: str,
    objective_metric: str,
    **kwargs,
) -> ObjectiveFunction:
    """
    创建目标函数的工厂方法

    Args:
        base_cfg: 基础配置
        model_name: 模型名称
        objective_metric: 优化目标
        **kwargs: 传递给 ObjectiveFunction 的其他参数

    Returns:
        ObjectiveFunction 实例
    """
    return ObjectiveFunction(
        base_cfg=base_cfg,
        model_name=model_name,
        objective_metric=objective_metric,
        **kwargs,
    )
