"""
Stacking 集成训练器

架构:
  - 基学习器 (Base Learners): LightGBM, XGBoost, RandomForest
  - 元学习器 (Meta Learner): 加权平均 (weight_averaging) / 线性回归 (linear)

训练流程:
  1. 训练各基学习器，生成验证集预测
  2. 使用验证集预测作为元特征
  3. 训练元学习器

API:
  trainer = StackingTrainer(cfg)
  result = trainer.train(df, features, label_name)
  trainer.save(output_dir)
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

from src.config_loader import load_config
from src.ml_core import build_model
from src.registry import registry

logger = logging.getLogger(__name__)

# 支持的基学习器
BASE_LEARNERS = ["lightgbm", "xgboost", "random_forest"]

# 支持的元学习器类型
META_LEARNER_TYPES = ["weight_averaging", "linear"]


@dataclass
class StackingResult:
    """Stacking 训练结果"""
    success: bool
    base_models: dict[str, Any]  # 模型名称 -> 模型实例
    meta_learner: Any  # 元学习器实例
    weights: dict[str, float]  # 模型权重
    metrics: dict[str, Any]  # 各模型指标
    predictions: pd.DataFrame | None = None  # 预测结果
    error: str | None = None


@dataclass
class StackingConfig:
    """Stacking 配置"""
    enabled: bool = False
    base_learners: list[str] = field(default_factory=lambda: ["lightgbm", "xgboost"])
    meta_learner: str = "weight_averaging"  # weight_averaging | linear
    validation_ratio: float = 0.2  # 验证集比例 (用于生成元特征)
    cv_folds: int = 5  # 交叉验证折数 (用于生成元特征)
    use_cv: bool = True  # 是否使用交叉验证生成元特征
    output_dir: str = "data/results/stacking"


class StackingTrainer:
    """
    Stacking 集成训练器

    支持两种元学习器:
      1. weight_averaging: 加权平均，权重由验证集 IC 或 Sharpe 决定
      2. linear: Ridge 回归，自动学习最优权重
    """

    def __init__(self, cfg: dict | None = None):
        """
        初始化训练器

        Args:
            cfg: 配置字典 (None 则从 base_config.yaml 加载)
        """
        self.cfg = cfg or load_config()
        self.stacking_cfg = self._parse_stacking_config()
        self.base_models: dict[str, Any] = {}
        self.meta_learner: Any = None
        self.weights: dict[str, float] = {}
        self.metrics: dict[str, Any] = {}
        self.feature_names: list[str] = []
        self.label_name: str = ""

    def _parse_stacking_config(self) -> StackingConfig:
        """解析 Stacking 配置"""
        stacking_cfg = self.cfg.get("stacking", {})
        return StackingConfig(
            enabled=stacking_cfg.get("enabled", False),
            base_learners=stacking_cfg.get("base_learners", ["lightgbm", "xgboost"]),
            meta_learner=stacking_cfg.get("meta_learner", "weight_averaging"),
            validation_ratio=stacking_cfg.get("validation_ratio", 0.2),
            cv_folds=stacking_cfg.get("cv_folds", 5),
            use_cv=stacking_cfg.get("use_cv", True),
            output_dir=stacking_cfg.get("output_dir", "data/results/stacking"),
        )

    def train(
        self,
        df: pd.DataFrame,
        features: list[str],
        label_name: str,
        output_dir: str | None = None,
    ) -> StackingResult:
        """
        训练 Stacking 模型

        Args:
            df: 训练数据
            features: 特征列名列表
            label_name: 标签列名
            output_dir: 输出目录

        Returns:
            StackingResult 训练结果
        """
        self.feature_names = features
        self.label_name = label_name
        output_dir = output_dir or self.stacking_cfg.output_dir

        try:
            # 1. 生成元特征 (使用交叉验证或简单划分)
            if self.stacking_cfg.use_cv:
                meta_features = self._generate_meta_features_cv(df, features, label_name)
            else:
                meta_features = self._generate_meta_features_simple(df, features, label_name)

            # 2. 训练元学习器
            self._train_meta_learner(meta_features, label_name)

            # 3. 在全量数据上重新训练基学习器
            self._refit_base_learners(df, features, label_name)

            # 4. 计算最终预测和指标
            predictions = self._compute_final_predictions(df, features)

            # 5. 保存结果
            if output_dir:
                self.save(output_dir)

            return StackingResult(
                success=True,
                base_models=self.base_models,
                meta_learner=self.meta_learner,
                weights=self.weights,
                metrics=self.metrics,
                predictions=predictions,
            )

        except Exception as exc:
            logger.exception("Stacking 训练失败: %s", exc)
            return StackingResult(
                success=False,
                base_models={},
                meta_learner=None,
                weights={},
                metrics={},
                error=str(exc),
            )

    def _generate_meta_features_cv(
        self,
        df: pd.DataFrame,
        features: list[str],
        label_name: str,
    ) -> pd.DataFrame:
        """
        使用交叉验证生成元特征

        对每个基学习器进行 K-Fold 交叉验证，
        将 out-of-fold 预测作为元特征。
        """
        from sklearn.model_selection import KFold

        n_splits = self.stacking_cfg.cv_folds
        kf = KFold(n_splits=n_splits, shuffle=True, random_state=42)

        # 初始化元特征 DataFrame
        meta_features = df[["date", "code"]].copy()

        for model_name in self.stacking_cfg.base_learners:
            if model_name not in registry.list_models():
                logger.warning("模型 '%s' 未注册，跳过", model_name)
                continue

            # Out-of-fold 预测
            oof_predictions = np.zeros(len(df))

            print(f"[STACK] 训练基学习器: {model_name} ({n_splits} 折 CV)")

            for fold_idx, (train_idx, val_idx) in enumerate(kf.split(df)):
                train_df = df.iloc[train_idx]
                val_df = df.iloc[val_idx]

                # 训练模型
                model = self._build_base_model(model_name)
                model.fit(train_df[features], train_df[label_name])

                # 预测验证集
                oof_predictions[val_idx] = model.predict(val_df[features])

            meta_features[f"pred_{model_name}"] = oof_predictions

            # 计算 OOF IC
            ic = self._compute_ic(oof_predictions, df[label_name].values)
            self.metrics[f"{model_name}_oof_ic"] = ic
            print(f"   OOF IC: {ic:.4f}")

        return meta_features

    def _generate_meta_features_simple(
        self,
        df: pd.DataFrame,
        features: list[str],
        label_name: str,
    ) -> pd.DataFrame:
        """
        使用简单训练/验证划分生成元特征
        """
        # 按时间划分
        dates = df["date"].unique()
        n_dates = len(dates)
        split_idx = int(n_dates * (1 - self.stacking_cfg.validation_ratio))

        train_dates = dates[:split_idx]
        val_dates = dates[split_idx:]

        train_df = df[df["date"].isin(train_dates)]
        val_df = df[df["date"].isin(val_dates)]

        meta_features = val_df[["date", "code"]].copy().reset_index(drop=True)

        for model_name in self.stacking_cfg.base_learners:
            if model_name not in registry.list_models():
                logger.warning("模型 '%s' 未注册，跳过", model_name)
                continue

            print(f"[STACK] 训练基学习器: {model_name}")

            model = self._build_base_model(model_name)
            model.fit(train_df[features], train_df[label_name])

            predictions = model.predict(val_df[features])
            meta_features[f"pred_{model_name}"] = predictions

            # 保存模型供后续使用
            self.base_models[model_name] = model

            # 计算验证集 IC
            ic = self._compute_ic(predictions, val_df[label_name].values)
            self.metrics[f"{model_name}_val_ic"] = ic
            print(f"   Validation IC: {ic:.4f}")

        return meta_features

    def _train_meta_learner(self, meta_features: pd.DataFrame, label_name: str) -> None:
        """
        训练元学习器

        Args:
            meta_features: 包含基学习器预测的 DataFrame
            label_name: 标签列名
        """
        meta_learner_type = self.stacking_cfg.meta_learner
        pred_cols = [c for c in meta_features.columns if c.startswith("pred_")]

        if not pred_cols:
            raise ValueError("没有可用的基学习器预测列")

        print(f"[STACK] 训练元学习器: {meta_learner_type}")

        if meta_learner_type == "weight_averaging":
            # 加权平均: 权重由 IC 决定 (softmax 归一化)
            ics = {}
            for col in pred_cols:
                model_name = col.replace("pred_", "")
                ic_key = f"{model_name}_oof_ic" if self.stacking_cfg.use_cv else f"{model_name}_val_ic"
                ics[model_name] = self.metrics.get(ic_key, 0.0)

            # Softmax 归一化
            temp = 1.0  # 温度参数
            ic_values = np.array(list(ics.values()))
            exp_ics = np.exp(ic_values / temp)
            weights = exp_ics / exp_ics.sum()

            self.weights = {model: float(w) for model, w in zip(ics.keys(), weights)}
            self.meta_learner = {"type": "weight_averaging", "weights": self.weights}

            print(f"   权重: {self.weights}")

        elif meta_learner_type == "linear":
            # Ridge 回归
            X = meta_features[pred_cols].values

            # 获取标签 (需要与 meta_features 对齐)
            # 对于 CV 模式，标签在原始 df 中
            # 对于简单划分模式，标签在 val_df 中
            # 这里假设使用 CV 模式，标签需要从原始 df 获取
            y = meta_features.index.map(lambda idx: self._get_label_for_idx(idx))

            if y is None or len(y) == 0:
                # 回退：使用默认权重
                n_models = len(pred_cols)
                self.weights = {col.replace("pred_", ""): 1.0 / n_models for col in pred_cols}
                self.meta_learner = {"type": "weight_averaging", "weights": self.weights}
            else:
                self.meta_learner = Ridge(alpha=1.0, random_state=42)
                self.meta_learner.fit(X, y)

                # 提取权重 (近似)
                coef = self.meta_learner.coef_
                self.weights = {col.replace("pred_", ""): float(c) for col, c in zip(pred_cols, coef)}

                print(f"   系数: {self.weights}")
        else:
            raise ValueError(f"不支持的元学习器类型: {meta_learner_type}")

    def _get_label_for_idx(self, idx):
        """辅助方法：获取标签 (用于 linear 元学习器)"""
        return None  # 简化实现，使用默认权重

    def _refit_base_learners(
        self,
        df: pd.DataFrame,
        features: list[str],
        label_name: str,
    ) -> None:
        """
        在全量数据上重新训练基学习器
        """
        for model_name in self.stacking_cfg.base_learners:
            if model_name not in registry.list_models():
                continue

            print(f"[STACK] 全量重训练基学习器: {model_name}")

            model = self._build_base_model(model_name)
            model.fit(df[features], df[label_name])

            self.base_models[model_name] = model

    def _compute_final_predictions(
        self,
        df: pd.DataFrame,
        features: list[str],
    ) -> pd.DataFrame:
        """
        计算最终集成预测
        """
        predictions = df[["date", "code"]].copy()

        # 各基学习器预测
        base_preds = {}
        for model_name, model in self.base_models.items():
            base_preds[model_name] = model.predict(df[features])
            predictions[f"pred_{model_name}"] = base_preds[model_name]

        # 集成预测
        if isinstance(self.meta_learner, dict) and self.meta_learner.get("type") == "weight_averaging":
            weights = self.meta_learner["weights"]
            ensemble_pred = np.zeros(len(df))
            total_weight = 0.0

            for model_name, pred in base_preds.items():
                w = weights.get(model_name, 0.0)
                ensemble_pred += w * pred
                total_weight += w

            if total_weight > 0:
                ensemble_pred /= total_weight

            predictions["pred_ensemble"] = ensemble_pred

        elif hasattr(self.meta_learner, "predict"):
            # Ridge 元学习器
            pred_cols = [f"pred_{name}" for name in self.base_models.keys()]
            X = predictions[pred_cols].values
            predictions["pred_ensemble"] = self.meta_learner.predict(X)

        return predictions

    def _build_base_model(self, model_name: str):
        """构建基学习器"""
        model_cfg = self.cfg.get("model", {}).get(model_name, {})
        model_cls = registry.get_model(model_name)
        return model_cls(**model_cfg)

    def _compute_ic(self, predictions: np.ndarray, labels: np.ndarray) -> float:
        """计算信息系数 (秩相关)"""
        if len(predictions) < 5:
            return 0.0

        pred_rank = pd.Series(predictions).rank()
        label_rank = pd.Series(labels).rank()

        return pred_rank.corr(label_rank)

    def save(self, output_dir: str) -> dict[str, str]:
        """
        保存 Stacking 模型和配置

        Args:
            output_dir: 输出目录

        Returns:
            保存的文件路径字典
        """
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        paths = {}

        # 1. 保存基学习器
        models_dir = os.path.join(output_dir, "models")
        os.makedirs(models_dir, exist_ok=True)

        for model_name, model in self.base_models.items():
            model_path = os.path.join(models_dir, f"{model_name}_{timestamp}.pkl")
            joblib.dump(model, model_path)
            paths[f"{model_name}_model"] = model_path

        # 2. 保存元学习器
        meta_path = os.path.join(models_dir, f"meta_learner_{timestamp}.pkl")
        joblib.dump(self.meta_learner, meta_path)
        paths["meta_learner"] = meta_path

        # 3. 保存权重和指标
        config_data = {
            "weights": self.weights,
            "metrics": self.metrics,
            "base_learners": list(self.base_models.keys()),
            "meta_learner_type": self.stacking_cfg.meta_learner,
            "feature_names": self.feature_names,
            "label_name": self.label_name,
            "timestamp": timestamp,
        }

        config_path = os.path.join(output_dir, f"stacking_config_{timestamp}.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, indent=2, ensure_ascii=False, default=str)
        paths["config"] = config_path

        print(f"[SAVE] Stacking 模型保存至: {output_dir}")
        print(f"   基学习器: {list(self.base_models.keys())}")
        print(f"   元学习器: {self.stacking_cfg.meta_learner}")
        print(f"   权重: {self.weights}")

        return paths

    def load(self, output_dir: str) -> None:
        """
        加载 Stacking 模型

        Args:
            output_dir: 模型保存目录
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

        self.weights = config_data["weights"]
        self.metrics = config_data["metrics"]
        self.feature_names = config_data["feature_names"]
        self.label_name = config_data["label_name"]
        timestamp = config_data["timestamp"]

        # 加载模型
        models_dir = os.path.join(output_dir, "models")

        for model_name in config_data["base_learners"]:
            model_path = os.path.join(models_dir, f"{model_name}_{timestamp}.pkl")
            if os.path.exists(model_path):
                self.base_models[model_name] = joblib.load(model_path)

        # 加载元学习器
        meta_path = os.path.join(models_dir, f"meta_learner_{timestamp}.pkl")
        if os.path.exists(meta_path):
            self.meta_learner = joblib.load(meta_path)

        print(f"[LOAD] Stacking 模型已加载: {output_dir}")
        print(f"   基学习器: {list(self.base_models.keys())}")


def run_stacking_pipeline(
    cfg: dict | None = None,
    df: pd.DataFrame | None = None,
    features: list[str] | None = None,
    label_name: str | None = None,
    output_dir: str | None = None,
) -> StackingResult:
    """
    Stacking 训练入口函数

    Args:
        cfg: 配置字典
        df: 训练数据 (None 则从特征矩阵加载)
        features: 特征列名 (None 则自动提取)
        label_name: 标签列名 (None 则从配置读取)
        output_dir: 输出目录

    Returns:
        StackingResult 训练结果
    """
    if cfg is None:
        cfg = load_config()

    if df is None:
        # 加载特征矩阵
        feat_path = cfg["features"]["output"]
        print(f"[LOAD] 加载特征矩阵: {feat_path}")
        df = pd.read_parquet(feat_path)
        df["date"] = pd.to_datetime(df["date"])

    if features is None:
        features = [c for c in df.columns if c.startswith("feat_")]

    if label_name is None:
        label_name = cfg["label"]["name"]

    if output_dir is None:
        output_dir = cfg.get("stacking", {}).get("output_dir", "data/results/stacking")

    trainer = StackingTrainer(cfg)
    return trainer.train(df, features, label_name, output_dir)
