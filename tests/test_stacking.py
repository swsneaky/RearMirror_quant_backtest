"""
Stacking 模块测试

测试内容:
  - StackingTrainer 训练流程
  - StackingPredictor 预测功能
  - 配置解析
  - API 端点
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from src.stacking.stacking_trainer import (
    StackingConfig,
    StackingResult,
    StackingTrainer,
    run_stacking_pipeline,
)
from src.stacking.predictor import StackingPredictor


# ================================================================
# Fixtures
# ================================================================
@pytest.fixture
def sample_df():
    """创建测试数据"""
    np.random.seed(42)
    n_samples = 500
    n_features = 10

    dates = pd.date_range("2020-01-01", periods=100, freq="D")
    codes = [f"stock_{i:03d}" for i in range(5)]

    rows = []
    for date in dates:
        for code in codes:
            rows.append({
                "date": date,
                "code": code,
                "industry": "test",
            })

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])

    # 添加特征
    for i in range(n_features):
        df[f"feat_{i}"] = np.random.randn(len(df))

    # 添加标签
    df["label_5d_ret"] = np.random.randn(len(df)) * 0.02

    return df


@pytest.fixture
def sample_features(sample_df):
    """获取特征列名"""
    return [c for c in sample_df.columns if c.startswith("feat_")]


@pytest.fixture
def sample_config():
    """创建测试配置"""
    return {
        "model": {
            "active": "xgboost",
            "xgboost": {
                "n_estimators": 10,
                "max_depth": 3,
                "learning_rate": 0.1,
                "n_jobs": 1,
            },
            "lightgbm": {
                "n_estimators": 10,
                "max_depth": 3,
                "learning_rate": 0.1,
                "n_jobs": 1,
            },
        },
        "stacking": {
            "enabled": True,
            "base_learners": ["lightgbm", "xgboost"],
            "meta_learner": "weight_averaging",
            "cv_folds": 3,
            "use_cv": True,
            "output_dir": "data/results/stacking_test",
        },
        "label": {
            "name": "label_5d_ret",
        },
    }


@pytest.fixture
def temp_output_dir():
    """创建临时输出目录"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


# ================================================================
# Unit Tests
# ================================================================
class TestStackingConfig:
    """测试 StackingConfig 配置解析"""

    def test_default_config(self):
        """测试默认配置"""
        config = StackingConfig()

        assert config.enabled is False
        assert config.base_learners == ["lightgbm", "xgboost"]
        assert config.meta_learner == "weight_averaging"
        assert config.cv_folds == 5
        assert config.use_cv is True

    def test_custom_config(self):
        """测试自定义配置"""
        config = StackingConfig(
            enabled=True,
            base_learners=["xgboost"],
            meta_learner="linear",
            cv_folds=3,
        )

        assert config.enabled is True
        assert config.base_learners == ["xgboost"]
        assert config.meta_learner == "linear"
        assert config.cv_folds == 3


class TestStackingTrainer:
    """测试 StackingTrainer"""

    def test_init(self, sample_config):
        """测试初始化"""
        trainer = StackingTrainer(sample_config)

        assert trainer.stacking_cfg.enabled is True
        assert "lightgbm" in trainer.stacking_cfg.base_learners
        assert "xgboost" in trainer.stacking_cfg.base_learners

    def test_train_cv_mode(self, sample_df, sample_features, sample_config, temp_output_dir):
        """测试 CV 模式训练"""
        sample_config["stacking"]["use_cv"] = True
        sample_config["stacking"]["output_dir"] = temp_output_dir

        trainer = StackingTrainer(sample_config)
        result = trainer.train(
            sample_df,
            sample_features,
            "label_5d_ret",
            output_dir=temp_output_dir,
        )

        assert result.success is True
        assert len(result.base_models) == 2
        assert result.meta_learner is not None
        assert len(result.weights) == 2
        assert result.predictions is not None

    def test_train_simple_mode(self, sample_df, sample_features, sample_config, temp_output_dir):
        """测试简单划分模式训练"""
        sample_config["stacking"]["use_cv"] = False
        sample_config["stacking"]["output_dir"] = temp_output_dir

        trainer = StackingTrainer(sample_config)
        result = trainer.train(
            sample_df,
            sample_features,
            "label_5d_ret",
            output_dir=temp_output_dir,
        )

        assert result.success is True
        assert len(result.base_models) == 2

    def test_save_and_load(self, sample_df, sample_features, sample_config, temp_output_dir):
        """测试保存和加载"""
        sample_config["stacking"]["output_dir"] = temp_output_dir

        trainer = StackingTrainer(sample_config)
        result = trainer.train(
            sample_df,
            sample_features,
            "label_5d_ret",
            output_dir=temp_output_dir,
        )

        assert result.success is True

        # 检查文件是否存在
        assert os.path.exists(os.path.join(temp_output_dir, "models"))

        # 加载
        new_trainer = StackingTrainer(sample_config)
        new_trainer.load(temp_output_dir)

        assert len(new_trainer.base_models) == 2
        assert new_trainer.label_name == "label_5d_ret"

    def test_compute_ic(self, sample_config):
        """测试 IC 计算"""
        trainer = StackingTrainer(sample_config)

        pred = np.array([0.1, 0.2, 0.3, 0.4, 0.5])
        label = np.array([0.2, 0.1, 0.4, 0.3, 0.6])

        ic = trainer._compute_ic(pred, label)

        # IC 应该在 -1 到 1 之间
        assert -1 <= ic <= 1


class TestStackingPredictor:
    """测试 StackingPredictor"""

    def test_predict(self, sample_df, sample_features, sample_config, temp_output_dir):
        """测试预测功能"""
        # 先训练
        sample_config["stacking"]["output_dir"] = temp_output_dir
        trainer = StackingTrainer(sample_config)
        result = trainer.train(
            sample_df,
            sample_features,
            "label_5d_ret",
            output_dir=temp_output_dir,
        )

        assert result.success is True

        # 加载预测器
        predictor = StackingPredictor.from_dir(temp_output_dir)

        # 预测
        predictions = predictor.predict(sample_df.head(50), sample_features)

        assert "pred_ensemble" in predictions.columns
        assert "pred_lightgbm" in predictions.columns
        assert "pred_xgboost" in predictions.columns

    def test_get_feature_importance(self, sample_df, sample_features, sample_config, temp_output_dir):
        """测试特征重要性"""
        sample_config["stacking"]["output_dir"] = temp_output_dir
        trainer = StackingTrainer(sample_config)
        result = trainer.train(
            sample_df,
            sample_features,
            "label_5d_ret",
            output_dir=temp_output_dir,
        )

        predictor = StackingPredictor.from_dir(temp_output_dir)
        importance = predictor.get_feature_importance()

        assert len(importance) == len(sample_features)
        # 重要性应该归一化
        total = sum(importance.values())
        assert abs(total - 1.0) < 0.01

    def test_get_model_weights(self, sample_df, sample_features, sample_config, temp_output_dir):
        """测试模型权重"""
        sample_config["stacking"]["output_dir"] = temp_output_dir
        trainer = StackingTrainer(sample_config)
        result = trainer.train(
            sample_df,
            sample_features,
            "label_5d_ret",
            output_dir=temp_output_dir,
        )

        predictor = StackingPredictor.from_dir(temp_output_dir)
        weights = predictor.get_model_weights()

        assert "lightgbm" in weights
        assert "xgboost" in weights
        # 权重总和应接近 1
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.01

    def test_summary(self, sample_df, sample_features, sample_config, temp_output_dir):
        """测试摘要"""
        sample_config["stacking"]["output_dir"] = temp_output_dir
        trainer = StackingTrainer(sample_config)
        result = trainer.train(
            sample_df,
            sample_features,
            "label_5d_ret",
            output_dir=temp_output_dir,
        )

        predictor = StackingPredictor.from_dir(temp_output_dir)
        summary = predictor.summary()

        assert "base_models" in summary
        assert "weights" in summary
        assert "n_features" in summary


class TestRunStackingPipeline:
    """测试便捷函数"""

    def test_run_stacking_pipeline(self, sample_df, sample_features, sample_config, temp_output_dir):
        """测试 run_stacking_pipeline 函数"""
        sample_config["stacking"]["output_dir"] = temp_output_dir

        result = run_stacking_pipeline(
            cfg=sample_config,
            df=sample_df,
            features=sample_features,
            label_name="label_5d_ret",
            output_dir=temp_output_dir,
        )

        assert result.success is True
        assert len(result.base_models) == 2


# ================================================================
# API Tests
# ================================================================
class TestStackingAPI:
    """测试 Stacking API 端点"""

    @pytest.fixture
    def client(self):
        """创建测试客户端"""
        from fastapi.testclient import TestClient
        from api.main import app
        return TestClient(app)

    def test_get_stacking_status(self, client):
        """测试获取 Stacking 状态"""
        response = client.get("/api/stacking/status")

        assert response.status_code == 200
        data = response.json()

        assert "status" in data
        assert "available_models" in data

    def test_get_available_models(self, client):
        """测试获取可用模型"""
        response = client.get("/api/stacking/models")

        assert response.status_code == 200
        data = response.json()

        assert "models" in data
        assert "default_base_learners" in data

        # 检查已注册模型
        model_names = [m["name"] for m in data["models"]]
        assert "lightgbm" in model_names
        assert "xgboost" in model_names


# ================================================================
# Integration Tests
# ================================================================
class TestStackingIntegration:
    """集成测试"""

    def test_full_workflow(self, sample_df, sample_features, sample_config, temp_output_dir):
        """测试完整工作流"""
        sample_config["stacking"]["output_dir"] = temp_output_dir

        # 1. 训练
        trainer = StackingTrainer(sample_config)
        result = trainer.train(
            sample_df,
            sample_features,
            "label_5d_ret",
            output_dir=temp_output_dir,
        )

        assert result.success is True

        # 2. 加载预测器
        predictor = StackingPredictor.from_dir(temp_output_dir)

        # 3. 预测新数据
        new_data = sample_df.head(100).copy()
        predictions = predictor.predict(new_data, sample_features)

        # 4. 验证预测结果
        assert len(predictions) == 100
        assert "pred_ensemble" in predictions.columns

        # 5. 获取特征重要性
        importance = predictor.get_feature_importance()
        assert len(importance) > 0

        # 6. 获取模型权重
        weights = predictor.get_model_weights()
        assert len(weights) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
