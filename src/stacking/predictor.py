"""
Stacking 预测器

功能:
  - 加载已训练的 Stacking 模型
  - 对新数据进行集成预测
  - 支持单独获取各基学习器预测

API:
  predictor = StackingPredictor.from_dir(output_dir)
  predictions = predictor.predict(df, features)
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import joblib
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class StackingPredictor:
    """
    Stacking 预测器

    用于加载训练好的 Stacking 模型并进行预测。
    """

    def __init__(
        self,
        base_models: dict[str, Any],
        meta_learner: Any,
        weights: dict[str, float],
        feature_names: list[str],
        label_name: str,
    ):
        """
        初始化预测器

        Args:
            base_models: 基学习器字典 {name: model}
            meta_learner: 元学习器
            weights: 模型权重字典
            feature_names: 特征列名列表
            label_name: 标签列名
        """
        self.base_models = base_models
        self.meta_learner = meta_learner
        self.weights = weights
        self.feature_names = feature_names
        self.label_name = label_name

    @classmethod
    def from_dir(cls, output_dir: str) -> "StackingPredictor":
        """
        从目录加载 Stacking 模型

        Args:
            output_dir: 模型保存目录

        Returns:
            StackingPredictor 实例
        """
        # 找到最新的配置文件
        config_files = sorted([
            f for f in os.listdir(output_dir)
            if f.startswith("stacking_config_") and f.endswith(".json")
        ], reverse=True)

        if not config_files:
            raise FileNotFoundError(f"未找到 Stacking 配置文件: {output_dir}")

        config_path = os.path.join(output_dir, config_files[0])
        with open(config_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)

        weights = config_data["weights"]
        feature_names = config_data["feature_names"]
        label_name = config_data["label_name"]
        timestamp = config_data["timestamp"]

        # 加载基学习器
        base_models = {}
        models_dir = os.path.join(output_dir, "models")

        for model_name in config_data["base_learners"]:
            model_path = os.path.join(models_dir, f"{model_name}_{timestamp}.pkl")
            if os.path.exists(model_path):
                base_models[model_name] = joblib.load(model_path)
                logger.info("加载基学习器: %s", model_name)

        # 加载元学习器
        meta_learner = None
        meta_path = os.path.join(models_dir, f"meta_learner_{timestamp}.pkl")
        if os.path.exists(meta_path):
            meta_learner = joblib.load(meta_path)
            logger.info("加载元学习器")

        return cls(
            base_models=base_models,
            meta_learner=meta_learner,
            weights=weights,
            feature_names=feature_names,
            label_name=label_name,
        )

    def predict(
        self,
        df: pd.DataFrame,
        features: list[str] | None = None,
        return_base_predictions: bool = False,
    ) -> pd.DataFrame | tuple[pd.DataFrame, dict[str, np.ndarray]]:
        """
        进行 Stacking 预测

        Args:
            df: 待预测数据
            features: 特征列名 (None 则使用训练时的特征)
            return_base_predictions: 是否返回各基学习器预测

        Returns:
            包含预测结果的 DataFrame，或 (DataFrame, base_predictions_dict)
        """
        features = features or self.feature_names

        # 检查特征是否存在
        missing_features = [f for f in features if f not in df.columns]
        if missing_features:
            raise ValueError(f"缺失特征列: {missing_features}")

        # 各基学习器预测
        base_predictions = {}
        for model_name, model in self.base_models.items():
            pred = model.predict(df[features])
            base_predictions[model_name] = pred

        # 集成预测
        ensemble_pred = self._ensemble_predict(base_predictions)

        # 构建结果 DataFrame
        result = df[["date", "code"]].copy() if "date" in df.columns else pd.DataFrame(index=df.index)
        result["pred_ensemble"] = ensemble_pred

        for model_name, pred in base_predictions.items():
            result[f"pred_{model_name}"] = pred

        if return_base_predictions:
            return result, base_predictions

        return result

    def _ensemble_predict(self, base_predictions: dict[str, np.ndarray]) -> np.ndarray:
        """
        使用元学习器计算集成预测
        """
        if isinstance(self.meta_learner, dict) and self.meta_learner.get("type") == "weight_averaging":
            # 加权平均
            weights = self.meta_learner["weights"]
            ensemble_pred = np.zeros(len(list(base_predictions.values())[0]))
            total_weight = 0.0

            for model_name, pred in base_predictions.items():
                w = weights.get(model_name, 0.0)
                ensemble_pred += w * pred
                total_weight += w

            if total_weight > 0:
                ensemble_pred /= total_weight

            return ensemble_pred

        elif hasattr(self.meta_learner, "predict"):
            # Ridge 回归元学习器
            pred_cols = list(base_predictions.keys())
            X = np.column_stack([base_predictions[name] for name in pred_cols])
            return self.meta_learner.predict(X)

        else:
            # 回退到简单平均
            return np.mean(list(base_predictions.values()), axis=0)

    def get_feature_importance(self) -> dict[str, float]:
        """
        获取特征重要性 (各基学习器的平均)

        Returns:
            特征重要性字典 {feature_name: importance}
        """
        importance_sum = {}
        count = {}

        for model_name, model in self.base_models.items():
            if hasattr(model, "feature_importances_"):
                imp = model.feature_importances_
                for feat, val in zip(self.feature_names, imp):
                    importance_sum[feat] = importance_sum.get(feat, 0.0) + val
                    count[feat] = count.get(feat, 0) + 1

        # 平均
        avg_importance = {}
        for feat in importance_sum:
            avg_importance[feat] = importance_sum[feat] / count[feat]

        # 归一化
        total = sum(avg_importance.values())
        if total > 0:
            avg_importance = {k: v / total for k, v in avg_importance.items()}

        return dict(sorted(avg_importance.items(), key=lambda x: -x[1]))

    def get_model_weights(self) -> dict[str, float]:
        """
        获取模型权重

        Returns:
            模型权重字典
        """
        return self.weights.copy()

    def summary(self) -> dict[str, Any]:
        """
        获取预测器摘要信息
        """
        return {
            "base_models": list(self.base_models.keys()),
            "meta_learner_type": "weight_averaging" if isinstance(self.meta_learner, dict) else "linear",
            "weights": self.weights,
            "n_features": len(self.feature_names),
            "label_name": self.label_name,
        }


def load_stacking_predictor(output_dir: str) -> StackingPredictor:
    """
    加载 Stacking 预测器的便捷函数

    Args:
        output_dir: 模型保存目录

    Returns:
        StackingPredictor 实例
    """
    return StackingPredictor.from_dir(output_dir)
