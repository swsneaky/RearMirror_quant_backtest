"""
HPO 结果持久化工具

提供:
  - 结果导出 (Parquet / CSV)
  - 参数对比分析
  - 优化历史可视化数据
"""
import json
import logging
import os
from datetime import datetime
from typing import Any

import pandas as pd
import yaml

logger = logging.getLogger(__name__)


class HPOStorage:
    """
    HPO 结果存储管理器

    用法:
        storage = HPOStorage("data/results/hpo")
        storage.save_study(study, model_name, objective_metric)
        df = storage.load_trials(study_name)
    """

    def __init__(self, output_dir: str):
        """
        初始化存储管理器

        Args:
            output_dir: 输出目录
        """
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def save_study(
        self,
        study,
        model_name: str,
        objective_metric: str,
        extra_info: dict | None = None,
    ) -> dict[str, str]:
        """
        保存 Optuna Study 结果

        Args:
            study: Optuna Study 对象
            model_name: 模型名称
            objective_metric: 优化目标
            extra_info: 额外信息

        Returns:
            保存的文件路径字典
        """
        study_name = study.study_name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 1. 保存 trials DataFrame
        trials_df = study.trials_dataframe()
        trials_path = os.path.join(
            self.output_dir, f"{study_name}_trials_{timestamp}.parquet"
        )
        trials_df.to_parquet(trials_path, index=False, engine="pyarrow")

        # 2. 保存最优参数 YAML
        best_params_path = os.path.join(
            self.output_dir, f"{study_name}_best_{timestamp}.yaml"
        )
        best_params = study.best_trial.params if study.best_trial else {}
        best_value = study.best_trial.value if study.best_trial else None

        best_data = {
            "study_name": study_name,
            "model_name": model_name,
            "objective_metric": objective_metric,
            "best_value": best_value,
            "best_params": best_params,
            "timestamp": timestamp,
        }
        if extra_info:
            best_data["extra_info"] = extra_info

        with open(best_params_path, "w", encoding="utf-8") as f:
            yaml.dump(best_data, f, default_flow_style=False, allow_unicode=True)

        # 3. 保存完整摘要 JSON
        summary_path = os.path.join(
            self.output_dir, f"{study_name}_summary_{timestamp}.json"
        )
        summary = {
            "study_name": study_name,
            "model_name": model_name,
            "objective_metric": objective_metric,
            "direction": study.direction.name,
            "n_trials": len(study.trials),
            "best_trial": study.best_trial.number if study.best_trial else None,
            "best_value": best_value,
            "best_params": best_params,
            "timestamp": timestamp,
        }

        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False, default=str)

        return {
            "trials_path": trials_path,
            "best_params_path": best_params_path,
            "summary_path": summary_path,
        }

    def load_trials(self, study_name: str) -> pd.DataFrame:
        """
        加载试验记录

        Args:
            study_name: 研究名称

        Returns:
            trials DataFrame
        """
        pattern = f"{study_name}_trials_*.parquet"
        import glob
        files = sorted(glob.glob(os.path.join(self.output_dir, pattern)))

        if not files:
            raise FileNotFoundError(f"未找到试验记录: {pattern}")

        # 加载最新的
        latest = files[-1]
        return pd.read_parquet(latest)

    def load_best_params(self, study_name: str) -> dict:
        """
        加载最优参数

        Args:
            study_name: 研究名称

        Returns:
            最优参数字典
        """
        pattern = f"{study_name}_best_*.yaml"
        import glob
        files = sorted(glob.glob(os.path.join(self.output_dir, pattern)))

        if not files:
            raise FileNotFoundError(f"未找到最优参数文件: {pattern}")

        latest = files[-1]
        with open(latest, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def list_studies(self) -> list[dict]:
        """
        列出所有研究

        Returns:
            研究信息列表
        """
        import glob

        studies = []
        for summary_file in glob.glob(os.path.join(self.output_dir, "*_summary_*.json")):
            try:
                with open(summary_file, "r", encoding="utf-8") as f:
                    summary = json.load(f)
                studies.append(summary)
            except Exception as exc:
                logger.warning("加载摘要失败 %s: %s", summary_file, exc)

        # 按时间戳排序
        studies.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return studies

    def compare_studies(self, study_names: list[str]) -> pd.DataFrame:
        """
        对比多个研究的结果

        Args:
            study_names: 研究名称列表

        Returns:
            对比表格
        """
        records = []
        for name in study_names:
            try:
                best = self.load_best_params(name)
                records.append({
                    "study_name": name,
                    "model_name": best.get("model_name"),
                    "objective_metric": best.get("objective_metric"),
                    "best_value": best.get("best_value"),
                    "timestamp": best.get("timestamp"),
                })
            except FileNotFoundError:
                logger.warning("研究 %s 未找到", name)

        return pd.DataFrame(records)


def export_optimization_history(
    study,
    output_path: str,
) -> None:
    """
    导出优化历史

    Args:
        study: Optuna Study 对象
        output_path: 输出文件路径
    """
    df = study.trials_dataframe()

    # 选择关键列
    key_cols = ["number", "state", "value"]
    param_cols = [c for c in df.columns if c.startswith("params_")]
    attr_cols = [c for c in df.columns if c.startswith("user_attrs_")]

    keep_cols = key_cols + param_cols + attr_cols
    keep_cols = [c for c in keep_cols if c in df.columns]

    export_df = df[keep_cols].copy()

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    if output_path.endswith(".parquet"):
        export_df.to_parquet(output_path, index=False, engine="pyarrow")
    else:
        export_df.to_csv(output_path, index=False)

    logger.info("[HPO] 导出优化历史: %s (%d trials)", output_path, len(export_df))


def generate_param_importance(
    study,
    output_path: str | None = None,
) -> dict[str, float]:
    """
    计算参数重要性

    Args:
        study: Optuna Study 对象
        output_path: 输出文件路径 (可选)

    Returns:
        参数重要性字典
    """
    try:
        import optuna.importance

        importance = optuna.importance.get_param_importances(study)

        if output_path:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                yaml.dump(importance, f, default_flow_style=False)

        return importance

    except ImportError:
        logger.warning("optuna.importance 不可用，跳过参数重要性计算")
        return {}
    except Exception as exc:
        logger.warning("参数重要性计算失败: %s", exc)
        return {}
