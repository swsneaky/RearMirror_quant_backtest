"""
迭代 API 集成测试

测试端点:
  GET  /api/iterations              -- 获取迭代列表
  GET  /api/iterations/{id}         -- 获取迭代详情
  POST /api/iterations              -- 创建迭代并生成 MD
  GET  /api/iterations/{id}/brief   -- 获取 Markdown 简报
  GET  /api/iterations/{id}/artifacts -- 获取产物清单
  GET  /api/hpo/{study_name}/report -- 获取 HPO 研究报告
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pathlib import Path
import json
import shutil

from api.main import app


@pytest.fixture
def client():
    """创建测试客户端"""
    return TestClient(app)


@pytest.fixture
def test_iterations_dir(tmp_path):
    """创建临时迭代目录"""
    iterations_dir = tmp_path / "iterations"
    iterations_dir.mkdir(parents=True, exist_ok=True)

    # 创建测试迭代目录
    test_iter_dir = iterations_dir / "test_iteration_001"
    test_iter_dir.mkdir(parents=True, exist_ok=True)

    # 创建测试 summary
    summary_data = {
        "iteration_id": "test_iteration_001",
        "date": "2026-04-14",
        "stage": "analysis_and_delivery",
        "feature_set_id": "feature_set__test123",
        "label_set_id": "label_set__test456",
        "runtime_mode": "shared_machine",
        "conclusion": "测试迭代 - 集成测试用",
        "metrics": {
            "ann_return": 0.05,
            "ann_excess_return": -0.02,
            "information_ratio": -0.5,
        },
        "data_scale": {
            "feature_count": 50,
            "dataset_rows": 100000,
        },
        "recommendation": "keep_current_plan",
        "recommendation_reason": "集成测试",
        "premises": ["测试前提1", "测试前提2"],
        "artifacts": {
            "predictions": "data/results/results/predictions.parquet",
        },
    }

    with open(test_iter_dir / "iteration_result_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=2)

    return iterations_dir


class TestIterationsList:
    """测试迭代列表端点"""

    def test_list_iterations_returns_list(self, client):
        """测试获取迭代列表"""
        response = client.get("/api/iterations")

        assert response.status_code == 200
        data = response.json()
        assert "iterations" in data
        assert "total" in data
        assert isinstance(data["iterations"], list)

    def test_list_iterations_includes_sample(self, client):
        """测试迭代列表包含 sample_iteration_001"""
        response = client.get("/api/iterations")

        assert response.status_code == 200
        data = response.json()

        # 检查 sample_iteration_001 是否存在
        iteration_ids = [i["iteration_id"] for i in data["iterations"]]
        assert "sample_iteration_001" in iteration_ids


class TestIterationDetail:
    """测试迭代详情端点"""

    def test_get_iteration_detail(self, client):
        """测试获取迭代详情"""
        response = client.get("/api/iterations/sample_iteration_001")

        assert response.status_code == 200
        data = response.json()

        assert data["iteration_id"] == "sample_iteration_001"
        assert data["stage"] == "analysis_and_delivery"
        assert "metrics" in data
        assert "data_scale" in data
        assert "premises" in data

    def test_get_iteration_not_found(self, client):
        """测试获取不存在的迭代"""
        response = client.get("/api/iterations/nonexistent_iteration")

        assert response.status_code == 404


class TestIterationCreate:
    """测试创建迭代端点"""

    def test_create_iteration_minimal(self, client):
        """测试创建最小化迭代"""
        response = client.post("/api/iterations", json={
            "stage": "train_and_backtest",
            "conclusion": "测试创建迭代",
            "recommendation": "keep_current_plan",
        })

        assert response.status_code == 200
        data = response.json()

        assert "iteration_id" in data
        assert "json_path" in data
        assert "brief_path" in data
        assert data["message"].endswith("created successfully")

        # 清理：删除创建的迭代
        iteration_id = data["iteration_id"]
        client.delete(f"/api/iterations/{iteration_id}")

    def test_create_iteration_full(self, client):
        """测试创建完整迭代"""
        response = client.post("/api/iterations", json={
            "stage": "analysis_and_delivery",
            "conclusion": "完整测试迭代",
            "recommendation": "enter_next_round_factor_adjustment",
            "recommendation_reason": "业绩为负，需优化",
            "feature_set_id": "feature_set__test",
            "label_set_id": "label_set__test",
            "runtime_mode": "shared_machine",
            "metrics": {
                "ann_return": 0.08,
                "information_ratio": 1.2,
            },
            "data_scale": {
                "feature_count": 100,
            },
            "premises": ["测试前提"],
        })

        assert response.status_code == 200
        data = response.json()

        # 验证文件已创建
        json_path = Path(data["json_path"])
        brief_path = Path(data["brief_path"])

        assert json_path.exists()
        assert brief_path.exists()

        # 清理
        iteration_id = data["iteration_id"]
        client.delete(f"/api/iterations/{iteration_id}")


class TestIterationBrief:
    """测试迭代简报端点"""

    def test_get_iteration_brief(self, client):
        """测试获取迭代 Markdown 简报"""
        response = client.get("/api/iterations/sample_iteration_001/brief")

        assert response.status_code == 200
        data = response.json()

        assert data["iteration_id"] == "sample_iteration_001"
        assert data["format"] == "markdown"
        assert "brief" in data

        # 验证 Markdown 内容
        brief = data["brief"]
        assert "# 迭代结果简报" in brief
        # 检查包含关键内容（兼容现有格式）
        assert "analysis_and_delivery" in brief

    def test_get_brief_not_found(self, client):
        """测试获取不存在迭代的简报"""
        response = client.get("/api/iterations/nonexistent/brief")

        assert response.status_code == 404


class TestIterationArtifacts:
    """测试迭代产物端点"""

    def test_get_artifacts(self, client):
        """测试获取产物清单"""
        response = client.get("/api/iterations/sample_iteration_001/artifacts")

        assert response.status_code == 200
        data = response.json()

        assert data["iteration_id"] == "sample_iteration_001"
        assert "artifacts" in data
        assert "all_exist" in data
        assert "missing" in data

    def test_artifacts_not_found(self, client):
        """测试获取不存在迭代的产物"""
        response = client.get("/api/iterations/nonexistent/artifacts")

        assert response.status_code == 404


class TestHPOReport:
    """测试 HPO 研究报告端点"""

    def test_get_hpo_report(self, client):
        """测试获取 HPO 研究报告"""
        response = client.get("/api/hpo/hpo_xgboost_20260414_002703/report")

        assert response.status_code == 200
        data = response.json()

        assert data["study_name"] == "hpo_xgboost_20260414_002703"
        assert "summary" in data
        assert "report" in data
        assert data["format"] == "markdown"

        # 验证 Markdown 内容
        report = data["report"]
        assert "# HPO 研究报告" in report

    def test_hpo_report_not_found(self, client):
        """测试获取不存在的 HPO 研究报告"""
        response = client.get("/api/hpo/nonexistent_study/report")

        assert response.status_code == 404


class TestIntegration:
    """集成测试"""

    def test_full_iteration_workflow(self, client):
        """测试完整迭代工作流"""
        # 1. 创建迭代
        create_response = client.post("/api/iterations", json={
            "stage": "train_and_backtest",
            "conclusion": "集成测试迭代",
            "recommendation": "hpo_optimization",
            "metrics": {"sharpe_ratio": 1.5},
        })

        assert create_response.status_code == 200
        iteration_id = create_response.json()["iteration_id"]

        # 2. 获取迭代列表
        list_response = client.get("/api/iterations")
        assert list_response.status_code == 200
        assert iteration_id in [i["iteration_id"] for i in list_response.json()["iterations"]]

        # 3. 获取迭代详情
        detail_response = client.get(f"/api/iterations/{iteration_id}")
        assert detail_response.status_code == 200
        assert detail_response.json()["conclusion"] == "集成测试迭代"

        # 4. 获取简报
        brief_response = client.get(f"/api/iterations/{iteration_id}/brief")
        assert brief_response.status_code == 200
        assert "集成测试迭代" in brief_response.json()["brief"]

        # 5. 获取产物
        artifacts_response = client.get(f"/api/iterations/{iteration_id}/artifacts")
        assert artifacts_response.status_code == 200

        # 6. 删除迭代
        delete_response = client.delete(f"/api/iterations/{iteration_id}")
        assert delete_response.status_code == 200

        # 7. 验证已删除
        list_response2 = client.get("/api/iterations")
        assert iteration_id not in [i["iteration_id"] for i in list_response2.json()["iterations"]]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
