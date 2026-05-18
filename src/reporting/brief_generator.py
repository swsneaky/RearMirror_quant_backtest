"""
Markdown 简报生成器

生成 iteration_result_brief.md，符合 result_reporting.md 规范
"""
from __future__ import annotations

from typing import Optional
from datetime import datetime


def generate_iteration_brief(summary: dict) -> str:
    """
    生成迭代结果简报 Markdown

    Args:
        summary: iteration_result_summary.json 格式的字典

    Returns:
        Markdown 格式的简报字符串
    """
    iteration_id = summary.get("iteration_id", "unknown")
    date = summary.get("date", "")
    stage = summary.get("stage", "unknown")
    feature_set_id = summary.get("feature_set_id", "N/A")
    label_set_id = summary.get("label_set_id", "N/A")
    runtime_mode = summary.get("runtime_mode", "N/A")
    conclusion = summary.get("conclusion", "")
    metrics = summary.get("metrics", {})
    data_scale = summary.get("data_scale", {})
    recommendation = summary.get("recommendation", "")
    recommendation_reason = summary.get("recommendation_reason", "")
    premises = summary.get("premises", [])
    artifacts = summary.get("artifacts", {})
    hpo_study_name = summary.get("hpo_study_name")

    lines = []

    # 标题
    lines.append("# 迭代结果简报")
    lines.append("")

    # 基本信息
    lines.append("## 基本信息")
    lines.append("")
    lines.append("| 项目 | 值 |")
    lines.append("|------|-----|")
    lines.append(f"| 轮次 | {iteration_id} |")
    lines.append(f"| 日期 | {date} |")
    lines.append(f"| 阶段 | {stage} |")
    lines.append(f"| feature_set_id | {feature_set_id} |")
    lines.append(f"| label_set_id | {label_set_id} |")
    lines.append(f"| runtime_mode | {runtime_mode} |")
    if hpo_study_name:
        lines.append(f"| hpo_study | {hpo_study_name} |")
    lines.append("")

    # 核心结果
    lines.append("## 核心结果")
    lines.append("")
    lines.append(f"**结论：{conclusion}**")
    lines.append("")

    # 关键指标
    lines.append("## 关键指标")
    lines.append("")

    # 回测表现
    if metrics:
        lines.append("### 回测表现")
        lines.append("")
        lines.append("| 指标 | 值 | 说明 |")
        lines.append("|------|-----|------|")

        metric_labels = {
            "ann_return": ("年化收益", "绝对收益"),
            "ann_excess_return": ("年化超额收益", "相对基准"),
            "ann_volatility": ("年化波动率", "收益波动"),
            "information_ratio": ("信息比率", "风险调整后超额收益"),
            "sharpe_ratio": ("夏普比率", "风险调整后收益"),
            "max_drawdown": ("最大回撤", "最大损失"),
            "excess_max_drawdown": ("超额最大回撤", "相对基准最大偏离"),
            "avg_turnover": ("平均换手率", "每期换手"),
            "icir_mean": ("ICIR 均值", "因子预测能力"),
            "median_abs_icir": ("ICIR 绝对值中位数", "因子稳定性"),
        }

        for key, (label, desc) in metric_labels.items():
            value = metrics.get(key)
            if value is not None:
                if isinstance(value, float):
                    if "ratio" in key or "icir" in key:
                        formatted = f"{value:.2f}"
                    elif "turnover" in key:
                        formatted = f"{value:.1%}"
                    else:
                        formatted = f"{value:.2%}"
                else:
                    formatted = str(value)
                lines.append(f"| {label} | {formatted} | {desc} |")
        lines.append("")

    # 数据规模
    if data_scale:
        lines.append("### 数据规模")
        lines.append("")
        lines.append("| 项目 | 值 |")
        lines.append("|------|-----|")

        scale_labels = {
            "feature_count": "特征数",
            "dataset_rows": "数据集行数",
            "prediction_records": "预测记录数",
            "wfa_folds": "WFA 周期数",
        }

        for key, label in scale_labels.items():
            value = data_scale.get(key)
            if value is not None:
                lines.append(f"| {label} | {value:,} |")
        lines.append("")

    # 推荐动作
    lines.append("## 推荐动作")
    lines.append("")

    recommendation_labels = {
        "enter_next_round_factor_adjustment": "进入下一轮因子调整",
        "keep_current_plan": "保持当前方案",
        "rollback_fix": "回退修复",
        "manual_decision": "需要人工裁定",
        "hpo_optimization": "启动 HPO 优化",
    }

    rec_label = recommendation_labels.get(recommendation, recommendation)
    lines.append(f"**建议：{rec_label}**")
    lines.append("")

    if recommendation_reason:
        lines.append(f"原因：{recommendation_reason}")
        lines.append("")

    # 口径边界
    if premises:
        lines.append("## 口径边界")
        lines.append("")
        lines.append("**结果成立于以下前提下**：")
        lines.append("")
        for i, premise in enumerate(premises, 1):
            lines.append(f"{i}. {premise}")
        lines.append("")

    # 产物清单
    if artifacts:
        lines.append("## 产物清单")
        lines.append("")
        lines.append("```")
        for name, path in artifacts.items():
            lines.append(f"{name}: {path}")
        lines.append("```")
        lines.append("")

    # 下一阶段
    lines.append("## 下一阶段")
    lines.append("")
    next_stage = get_next_stage(stage)
    lines.append(f"当前阶段 **{stage}** 验收通过后：")
    lines.append(f"- 进入 **{next_stage}** 阶段")
    lines.append("")

    # 生成时间
    lines.append("---")
    lines.append(f"*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    lines.append("")

    return "\n".join(lines)


def get_next_stage(current_stage: str) -> str:
    """获取下一阶段名称"""
    stage_order = [
        "raw_to_canonical",
        "raw_feature",
        "factor_selection_and_neutralize",
        "label_and_dataset",
        "train_and_backtest",
        "analysis_and_delivery",
        "hyperparameter_optimization",
        "model_stacking",
        "formalization_and_promotion",
    ]

    try:
        idx = stage_order.index(current_stage)
        if idx < len(stage_order) - 1:
            return stage_order[idx + 1]
    except ValueError:
        pass

    return "待确定"


def generate_hpo_report(study_data: dict, trial_data: list = None) -> str:
    """
    生成 HPO 研究报告 Markdown

    Args:
        study_data: HPO summary.json 格式的字典
        trial_data: Trial 数据列表（可选）

    Returns:
        Markdown 格式的报告字符串
    """
    study_name = study_data.get("study_name", "unknown")
    model_name = study_data.get("model_name", "unknown")
    objective_metric = study_data.get("objective_metric", "unknown")
    direction = study_data.get("direction", "MAXIMIZE")
    n_trials = study_data.get("n_trials", 0)
    best_trial = study_data.get("best_trial")
    best_value = study_data.get("best_value")
    best_params = study_data.get("best_params", {})
    timestamp = study_data.get("timestamp", "")

    lines = []

    lines.append("# HPO 研究报告")
    lines.append("")

    # 基本信息
    lines.append("## 基本信息")
    lines.append("")
    lines.append("| 项目 | 值 |")
    lines.append("|------|-----|")
    lines.append(f"| 研究名称 | {study_name} |")
    lines.append(f"| 模型 | {model_name} |")
    lines.append(f"| 目标指标 | {objective_metric} |")
    lines.append(f"| 优化方向 | {direction} |")
    lines.append(f"| 总试验数 | {n_trials} |")

    if best_trial is not None:
        lines.append(f"| 最佳试验 | {best_trial} |")
    else:
        lines.append("| 最佳试验 | N/A |")

    if best_value is not None:
        lines.append(f"| 最佳值 | {best_value:.4f} |")
    else:
        lines.append("| 最佳值 | N/A |")

    lines.append(f"| 时间戳 | {timestamp} |")
    lines.append("")

    # 最佳参数
    if best_params:
        lines.append("## 最佳参数")
        lines.append("")
        lines.append("| 参数 | 值 |")
        lines.append("|------|-----|")
        for param, value in best_params.items():
            if isinstance(value, float):
                lines.append(f"| {param} | {value:.6f} |")
            else:
                lines.append(f"| {param} | {value} |")
        lines.append("")

    # Trial 详情（如果提供）
    if trial_data:
        lines.append("## Trial 详情")
        lines.append("")
        lines.append("| 编号 | 状态 | 值 |")
        lines.append("|------|------|-----|")
        for trial in trial_data[:10]:  # 只显示前 10 个
            number = trial.get("number", "?")
            state = trial.get("state", "?")
            value = trial.get("value")
            value_str = f"{value:.4f}" if value is not None else "N/A"
            lines.append(f"| {number} | {state} | {value_str} |")
        lines.append("")

    # 推荐动作
    lines.append("## 推荐动作")
    lines.append("")
    lines.append("- 使用最佳参数重新训练模型")
    lines.append("- 将最佳参数固化到配置文件")
    lines.append("- 创建迭代记录保存本次 HPO 结果")
    lines.append("")

    lines.append("---")
    lines.append(f"*生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    lines.append("")

    return "\n".join(lines)
