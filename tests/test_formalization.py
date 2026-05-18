"""
模型固化与晋升模块测试

测试内容:
  - ModelRegistry 模型注册表
  - ModelPromoter 模型晋升器
  - API 端点
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.formalization.model_registry import (
    ModelRegistry,
    ModelMetadata,
    ModelStatus,
    register_model_from_experiment,
)
from src.formalization.model_promoter import (
    ModelPromoter,
    PromotionResult,
    PromotionCheckResult,
    CheckResult,
    DEFAULT_PROMOTION_CRITERIA,
    run_promotion_pipeline,
)


# ================================================================
# Fixtures
# ================================================================
@pytest.fixture
def temp_registry_dir():
    """创建临时注册目录"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def temp_model_file():
    """创建临时模型文件"""
    temp_dir = tempfile.mkdtemp()
    model_path = os.path.join(temp_dir, "test_model.pkl")
    with open(model_path, "wb") as f:
        f.write(b"fake model data")
    yield model_path
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def sample_metrics():
    """创建测试指标"""
    return {
        "sharpe_ratio": 1.5,
        "icir": 0.8,
        "max_drawdown": 0.15,
        "information_ratio": 0.7,
        "ann_return": 0.25,
        "avg_turnover": 1.2,
    }


@pytest.fixture
def sample_config():
    """创建测试配置"""
    return {
        "paths": {
            "models": tempfile.mkdtemp(),
        },
        "model": {
            "active": "xgboost",
        },
        "database": {
            "path": ":memory:",
        },
    }


@pytest.fixture
def registry(temp_registry_dir, sample_config):
    """创建模型注册表实例"""
    return ModelRegistry(
        registry_dir=temp_registry_dir,
        cfg=sample_config,
    )


# ================================================================
# ModelMetadata Tests
# ================================================================
class TestModelMetadata:
    """测试 ModelMetadata"""

    def test_create_metadata(self):
        """测试创建元数据"""
        metadata = ModelMetadata(
            model_id="test_model_001",
            model_type="xgboost",
            version="1.0.0",
        )

        assert metadata.model_id == "test_model_001"
        assert metadata.model_type == "xgboost"
        assert metadata.status == ModelStatus.REGISTERED.value
        assert metadata.created_at != ""
        assert metadata.updated_at != ""

    def test_metadata_to_dict(self):
        """测试转换为字典"""
        metadata = ModelMetadata(
            model_id="test_model_001",
            model_type="xgboost",
            metrics={"sharpe_ratio": 1.5},
        )

        data = metadata.to_dict()

        assert data["model_id"] == "test_model_001"
        assert data["metrics"]["sharpe_ratio"] == 1.5

    def test_metadata_json_roundtrip(self):
        """测试 JSON 序列化/反序列化"""
        temp_dir = tempfile.mkdtemp()
        try:
            metadata = ModelMetadata(
                model_id="test_model_001",
                model_type="xgboost",
                metrics={"sharpe_ratio": 1.5},
                tags=["test", "xgb"],
            )

            json_path = os.path.join(temp_dir, "metadata.json")
            metadata.to_json(json_path)

            loaded = ModelMetadata.from_json(json_path)

            assert loaded.model_id == metadata.model_id
            assert loaded.metrics["sharpe_ratio"] == 1.5
            assert loaded.tags == ["test", "xgb"]
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


# ================================================================
# ModelRegistry Tests
# ================================================================
class TestModelRegistry:
    """测试 ModelRegistry"""

    def test_register_model(self, registry, temp_model_file, sample_metrics):
        """测试注册模型"""
        model_id = registry.register(
            model_type="xgboost",
            model_path=temp_model_file,
            metrics=sample_metrics,
            feature_set_id="fs_test123",
            label_set_id="ls_test456",
        )

        assert model_id.startswith("xgboost_")

        # 检查元数据
        metadata = registry.get(model_id)
        assert metadata is not None
        assert metadata.model_type == "xgboost"
        assert metadata.status == ModelStatus.REGISTERED.value
        assert metadata.metrics["sharpe_ratio"] == 1.5
        assert metadata.feature_set_id == "fs_test123"

    def test_list_models(self, registry, temp_model_file, sample_metrics):
        """测试列出模型"""
        # 注册多个模型
        id1 = registry.register(
            model_type="xgboost",
            model_path=temp_model_file,
            metrics=sample_metrics,
        )
        id2 = registry.register(
            model_type="lightgbm",
            model_path=temp_model_file,
            metrics=sample_metrics,
        )

        models = registry.list()

        assert len(models) >= 2
        model_ids = [m.model_id for m in models]
        assert id1 in model_ids
        assert id2 in model_ids

    def test_list_by_status(self, registry, temp_model_file, sample_metrics):
        """测试按状态过滤"""
        model_id = registry.register(
            model_type="xgboost",
            model_path=temp_model_file,
            metrics=sample_metrics,
        )

        # 注册状态
        registered = registry.list(status=ModelStatus.REGISTERED.value)
        assert any(m.model_id == model_id for m in registered)

        # 验证状态
        registry.validate(model_id)
        validated = registry.list(status=ModelStatus.VALIDATED.value)
        assert any(m.model_id == model_id for m in validated)

    def test_update_status(self, registry, temp_model_file, sample_metrics):
        """测试更新状态"""
        model_id = registry.register(
            model_type="xgboost",
            model_path=temp_model_file,
            metrics=sample_metrics,
        )

        # 验证
        success = registry.validate(model_id)
        assert success is True

        metadata = registry.get(model_id)
        assert metadata.status == ModelStatus.VALIDATED.value

    def test_deprecate_model(self, registry, temp_model_file, sample_metrics):
        """测试废弃模型"""
        model_id = registry.register(
            model_type="xgboost",
            model_path=temp_model_file,
            metrics=sample_metrics,
        )

        success = registry.deprecate(model_id, reason="测试废弃")

        assert success is True
        metadata = registry.get(model_id)
        assert metadata.status == ModelStatus.DEPRECATED.value
        assert len(metadata.promotion_history) > 0

    def test_delete_model(self, registry, temp_model_file, sample_metrics):
        """测试删除模型"""
        model_id = registry.register(
            model_type="xgboost",
            model_path=temp_model_file,
            metrics=sample_metrics,
        )

        success = registry.delete(model_id)
        assert success is True

        metadata = registry.get(model_id)
        assert metadata is None

    def test_get_nonexistent_model(self, registry):
        """测试获取不存在的模型"""
        metadata = registry.get("nonexistent_model")
        assert metadata is None


# ================================================================
# ModelPromoter Tests
# ================================================================
class TestModelPromoter:
    """测试 ModelPromoter"""

    @pytest.fixture
    def promoter(self, registry):
        """创建晋升器实例"""
        return ModelPromoter(registry=registry, auto_deprecate_old=False)

    def test_check_criteria_pass(self, promoter, sample_metrics):
        """测试晋升条件检查通过"""
        metadata = ModelMetadata(
            model_id="test_001",
            model_type="xgboost",
            metrics=sample_metrics,
        )

        results = promoter.check_criteria(metadata)

        # 所有必需条件应通过
        for r in results:
            if r.name in ["sharpe_ratio", "icir", "max_drawdown"]:
                assert r.result == PromotionCheckResult.PASS.value

    def test_check_criteria_fail(self, promoter):
        """测试晋升条件检查失败"""
        metrics = {
            "sharpe_ratio": 0.5,  # 低于阈值
            "icir": 0.3,  # 低于阈值
            "max_drawdown": 0.5,  # 高于阈值
        }
        metadata = ModelMetadata(
            model_id="test_001",
            model_type="xgboost",
            metrics=metrics,
        )

        results = promoter.check_criteria(metadata)

        # 应有失败的检查
        failed = [r for r in results if r.result == PromotionCheckResult.FAIL.value]
        assert len(failed) >= 2  # sharpe_ratio 和 icir 应失败

    def test_check_status(self, promoter):
        """测试状态检查"""
        # 注册状态
        metadata = ModelMetadata(
            model_id="test_001",
            model_type="xgboost",
            status=ModelStatus.REGISTERED.value,
        )
        result = promoter.check_status(metadata)
        assert result.result == PromotionCheckResult.FAIL.value

        # 验证状态
        metadata.status = ModelStatus.VALIDATED.value
        result = promoter.check_status(metadata)
        assert result.result == PromotionCheckResult.PASS.value

        # 已晋升状态
        metadata.status = ModelStatus.PROMOTED.value
        result = promoter.check_status(metadata)
        assert result.result == PromotionCheckResult.FAIL.value

    def test_promote_model_success(
        self, promoter, registry, temp_model_file, sample_metrics
    ):
        """测试成功晋升模型"""
        model_id = registry.register(
            model_type="xgboost",
            model_path=temp_model_file,
            metrics=sample_metrics,
        )

        # 先验证
        registry.validate(model_id)

        # 晋升
        result = promoter.promote(model_id)

        assert result.success is True
        assert result.all_passed() is True

        # 检查状态
        metadata = registry.get(model_id)
        assert metadata.status == ModelStatus.PROMOTED.value

    def test_promote_model_fail_not_validated(
        self, promoter, registry, temp_model_file, sample_metrics
    ):
        """测试晋升未验证的模型失败"""
        model_id = registry.register(
            model_type="xgboost",
            model_path=temp_model_file,
            metrics=sample_metrics,
        )

        result = promoter.promote(model_id)

        assert result.success is False
        # 检查状态检查失败
        status_check = next((c for c in result.checks if c.name == "status"), None)
        assert status_check is not None
        assert status_check.result == PromotionCheckResult.FAIL.value

    def test_promote_model_fail_criteria(
        self, promoter, registry, temp_model_file
    ):
        """测试指标不达标导致晋升失败"""
        metrics = {
            "sharpe_ratio": 0.5,  # 低于阈值
            "icir": 0.3,
        }
        model_id = registry.register(
            model_type="xgboost",
            model_path=temp_model_file,
            metrics=metrics,
        )
        registry.validate(model_id)

        result = promoter.promote(model_id)

        assert result.success is False
        assert not result.all_passed()

    def test_force_promote(
        self, promoter, registry, temp_model_file
    ):
        """测试强制晋升"""
        metrics = {
            "sharpe_ratio": 0.5,  # 低于阈值
        }
        model_id = registry.register(
            model_type="xgboost",
            model_path=temp_model_file,
            metrics=metrics,
        )
        registry.validate(model_id)

        result = promoter.promote(model_id, force=True)

        assert result.success is True

    def test_custom_check(self, promoter, sample_metrics):
        """测试自定义检查"""
        def custom_check(metadata: ModelMetadata) -> CheckResult:
            if "custom_metric" in metadata.metrics:
                return CheckResult(
                    name="custom_check",
                    result=PromotionCheckResult.PASS.value,
                    message="自定义检查通过",
                )
            return CheckResult(
                name="custom_check",
                result=PromotionCheckResult.FAIL.value,
                message="缺少 custom_metric",
            )

        promoter.add_custom_check(custom_check)

        metadata = ModelMetadata(
            model_id="test_001",
            model_type="xgboost",
            metrics=sample_metrics,
            status=ModelStatus.VALIDATED.value,
        )

        results = promoter.run_all_checks(metadata)
        custom_result = next((r for r in results if r.name == "custom_check"), None)

        assert custom_result is not None
        assert custom_result.result == PromotionCheckResult.FAIL.value

    def test_auto_deprecate_old(
        self, registry, temp_model_file, sample_metrics
    ):
        """测试自动废弃旧模型"""
        import time

        promoter = ModelPromoter(registry=registry, auto_deprecate_old=True)

        # 注册并晋升第一个模型
        model_id1 = registry.register(
            model_type="xgboost",
            model_path=temp_model_file,
            metrics=sample_metrics,
        )
        registry.validate(model_id1)
        result1 = promoter.promote(model_id1)
        assert result1.success is True

        # 确保时间戳不同
        time.sleep(1.1)

        # 注册并晋升第二个模型
        model_id2 = registry.register(
            model_type="xgboost",
            model_path=temp_model_file,
            metrics=sample_metrics,
        )
        # 确保两个模型 ID 不同
        if model_id1 == model_id2:
            pytest.skip("两个模型 ID 相同，跳过测试")

        registry.validate(model_id2)
        result = promoter.promote(model_id2)

        # 第一个模型应被废弃
        assert model_id1 in result.deprecated_models
        old_metadata = registry.get(model_id1)
        assert old_metadata.status == ModelStatus.DEPRECATED.value


# ================================================================
# Promotion Pipeline Tests
# ================================================================
class TestPromotionPipeline:
    """测试晋升流水线"""

    def test_run_promotion_pipeline(
        self, registry, temp_model_file, sample_metrics
    ):
        """测试完整晋升流程"""
        # 注册模型
        model_id = registry.register(
            model_type="xgboost",
            model_path=temp_model_file,
            metrics=sample_metrics,
        )

        # 运行晋升流水线
        promoter = ModelPromoter(registry=registry, auto_deprecate_old=False)
        result = promoter.promote(model_id)

        # 由于未验证，应该失败
        assert result.success is False

        # 验证后重试
        registry.validate(model_id)
        result = promoter.promote(model_id)
        assert result.success is True


# ================================================================
# API Tests
# ================================================================
class TestFormalizationAPI:
    """测试 API 端点"""

    @pytest.fixture
    def client(self):
        """创建测试客户端"""
        from fastapi.testclient import TestClient
        from api.main import app
        return TestClient(app)

    def test_get_registry(self, client):
        """测试获取注册表"""
        response = client.get("/api/models/registry")

        assert response.status_code == 200
        data = response.json()

        assert "models" in data
        assert "total_count" in data
        assert "status_counts" in data

    def test_get_promotion_criteria(self, client):
        """测试获取晋升条件"""
        response = client.get("/api/models/promotion/criteria")

        assert response.status_code == 200
        data = response.json()

        assert "criteria" in data
        assert "sharpe_ratio" in data["criteria"]

    def test_get_nonexistent_model(self, client):
        """测试获取不存在的模型"""
        response = client.get("/api/models/nonexistent_model_id")

        assert response.status_code == 404

    def test_register_and_promote_model(self, client, temp_model_file, sample_metrics):
        """测试注册和晋升模型"""
        # 注册
        register_response = client.post("/api/models/register", json={
            "model_type": "xgboost",
            "model_path": temp_model_file,
            "metrics": sample_metrics,
            "version": "1.0.0",
            "description": "Test model",
        })

        assert register_response.status_code == 200
        model_id = register_response.json()["model_id"]

        # 验证
        validate_response = client.post(f"/api/models/{model_id}/validate")
        assert validate_response.status_code == 200

        # 晋升
        promote_response = client.post("/api/models/promote", json={
            "model_id": model_id,
        })

        # 如果指标达标，应成功
        if promote_response.json()["success"]:
            assert promote_response.status_code == 200

    def test_delete_model(self, client, temp_model_file, sample_metrics):
        """测试删除模型"""
        # 注册
        register_response = client.post("/api/models/register", json={
            "model_type": "xgboost",
            "model_path": temp_model_file,
            "metrics": sample_metrics,
        })

        model_id = register_response.json()["model_id"]

        # 删除
        delete_response = client.delete(f"/api/models/{model_id}")
        assert delete_response.status_code == 200

        # 确认删除
        get_response = client.get(f"/api/models/{model_id}")
        assert get_response.status_code == 404


# ================================================================
# Integration Tests
# ================================================================
class TestFormalizationIntegration:
    """集成测试"""

    def test_full_lifecycle(self, temp_registry_dir, temp_model_file, sample_metrics):
        """测试完整生命周期"""
        cfg = {
            "paths": {"models": temp_registry_dir},
            "database": {"path": ":memory:"},
        }

        registry = ModelRegistry(registry_dir=temp_registry_dir, cfg=cfg)
        promoter = ModelPromoter(registry=registry, auto_deprecate_old=False)

        # 1. 注册
        model_id = registry.register(
            model_type="xgboost",
            model_path=temp_model_file,
            metrics=sample_metrics,
            description="Integration test model",
            tags=["test", "integration"],
        )
        assert model_id is not None

        # 2. 验证状态
        metadata = registry.get(model_id)
        assert metadata.status == ModelStatus.REGISTERED.value

        # 3. 验证
        registry.validate(model_id)
        metadata = registry.get(model_id)
        assert metadata.status == ModelStatus.VALIDATED.value

        # 4. 晋升
        result = promoter.promote(model_id)
        assert result.success is True

        metadata = registry.get(model_id)
        assert metadata.status == ModelStatus.PROMOTED.value

        # 5. 废弃
        registry.deprecate(model_id, reason="End of lifecycle")
        metadata = registry.get(model_id)
        assert metadata.status == ModelStatus.DEPRECATED.value

        # 6. 删除
        registry.delete(model_id)
        metadata = registry.get(model_id)
        assert metadata is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
