"""
Stacking 状态 API

端点:
  GET  /api/stacking/status  -- 获取 Stacking 运行状态
  POST /api/stacking/train   -- 触发 Stacking 训练
  GET  /api/stacking/models  -- 获取可用模型列表
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/stacking", tags=["stacking"])

STACKING_DIR = Path("data/results/stacking")


# ================================================================
# Request/Response Models
# ================================================================
class StackingStatus(BaseModel):
    """Stacking 状态"""
    enabled: bool = False
    trained: bool = False
    base_learners: list[str] = []
    meta_learner: Optional[str] = None
    weights: dict[str, float] = {}
    last_trained: Optional[str] = None
    status: str = "not_trained"  # not_trained | trained | training


class StackingStatusResponse(BaseModel):
    """Stacking 状态响应"""
    status: StackingStatus
    available_models: list[str]


class StackingTrainRequest(BaseModel):
    """Stacking 训练请求"""
    base_learners: Optional[list[str]] = None  # None 则使用配置默认值
    meta_learner: Optional[str] = None
    cv_folds: Optional[int] = None
    output_dir: Optional[str] = None


class StackingTrainResponse(BaseModel):
    """Stacking 训练响应"""
    success: bool
    message: str
    output_dir: Optional[str] = None
    weights: Optional[dict[str, float]] = None
    metrics: Optional[dict[str, float]] = None


class ModelInfo(BaseModel):
    """模型信息"""
    name: str
    registered: bool
    has_config: bool


class ModelsResponse(BaseModel):
    """模型列表响应"""
    models: list[ModelInfo]
    default_base_learners: list[str]


# ================================================================
# Background Task
# ================================================================
def run_stacking_training(request: StackingTrainRequest):
    """后台运行 Stacking 训练"""
    from src.config_loader import load_config
    from src.stacking.stacking_trainer import run_stacking_pipeline

    cfg = load_config()

    # 覆盖配置
    if request.base_learners:
        cfg["stacking"]["base_learners"] = request.base_learners
    if request.meta_learner:
        cfg["stacking"]["meta_learner"] = request.meta_learner
    if request.cv_folds:
        cfg["stacking"]["cv_folds"] = request.cv_folds

    output_dir = request.output_dir or cfg.get("stacking", {}).get(
        "output_dir", "data/results/stacking"
    )

    try:
        result = run_stacking_pipeline(cfg=cfg, output_dir=output_dir)

        # 保存训练结果摘要
        summary = {
            "success": result.success,
            "base_learners": list(result.base_models.keys()),
            "meta_learner_type": request.meta_learner or cfg["stacking"]["meta_learner"],
            "weights": result.weights,
            "metrics": result.metrics,
            "timestamp": datetime.now().isoformat(),
        }

        summary_path = Path(output_dir) / "training_summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False, default=str)

        return result

    except Exception as exc:
        # 记录错误
        error_path = Path(output_dir) / "training_error.json"
        error_path.parent.mkdir(parents=True, exist_ok=True)
        with open(error_path, "w", encoding="utf-8") as f:
            json.dump({
                "error": str(exc),
                "timestamp": datetime.now().isoformat(),
            }, f, indent=2)
        raise


# ================================================================
# API Endpoints
# ================================================================
@router.get("/status", response_model=StackingStatusResponse)
async def get_stacking_status():
    """
    获取 Stacking 运行状态

    扫描输出目录，返回最新训练状态
    """
    from src.registry import registry

    status = StackingStatus()

    # 获取可用模型列表
    available_models = registry.list_models()

    # 检查是否有训练结果
    if STACKING_DIR.exists():
        # 查找配置文件
        config_files = sorted([
            f for f in os.listdir(STACKING_DIR)
            if f.startswith("stacking_config_") and f.endswith(".json")
        ], reverse=True)

        if config_files:
            config_path = STACKING_DIR / config_files[0]
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config_data = json.load(f)

                status.trained = True
                status.base_learners = config_data.get("base_learners", [])
                status.meta_learner = config_data.get("meta_learner_type")
                status.weights = config_data.get("weights", {})
                status.last_trained = config_data.get("timestamp")
                status.status = "trained"

            except Exception:
                pass

        # 检查是否正在训练
        training_flag = STACKING_DIR / ".training"
        if training_flag.exists():
            status.status = "training"

    return StackingStatusResponse(
        status=status,
        available_models=available_models,
    )


@router.post("/train", response_model=StackingTrainResponse)
async def train_stacking(
    request: StackingTrainRequest,
    background_tasks: BackgroundTasks,
):
    """
    触发 Stacking 训练

    训练在后台异步执行，可通过 /status 端点查询进度
    """
    from src.config_loader import load_config

    cfg = load_config()
    stacking_cfg = cfg.get("stacking", {})

    # 检查是否已启用
    if not stacking_cfg.get("enabled", False):
        # 自动启用
        cfg["stacking"]["enabled"] = True

    # 创建训练标记
    STACKING_DIR.mkdir(parents=True, exist_ok=True)
    training_flag = STACKING_DIR / ".training"
    with open(training_flag, "w") as f:
        f.write(datetime.now().isoformat())

    # 添加后台任务
    def train_and_cleanup():
        try:
            run_stacking_training(request)
        finally:
            # 清理训练标记
            if training_flag.exists():
                training_flag.unlink()

    background_tasks.add_task(train_and_cleanup)

    return StackingTrainResponse(
        success=True,
        message="Stacking 训练已启动，请通过 /api/stacking/status 查询进度",
        output_dir=str(STACKING_DIR),
    )


@router.get("/models", response_model=ModelsResponse)
async def get_available_models():
    """
    获取可用模型列表

    返回所有已注册的模型及其状态
    """
    from src.config_loader import load_config
    from src.registry import registry

    cfg = load_config()
    registered_models = registry.list_models()
    model_configs = cfg.get("model", {})

    models = []
    for name in registered_models:
        models.append(ModelInfo(
            name=name,
            registered=True,
            has_config=name in model_configs,
        ))

    default_base_learners = cfg.get("stacking", {}).get(
        "base_learners", ["lightgbm", "xgboost"]
    )

    return ModelsResponse(
        models=models,
        default_base_learners=default_base_learners,
    )


@router.delete("/models")
async def clear_stacking_models():
    """
    清理 Stacking 模型文件

    删除所有已保存的 Stacking 模型
    """
    import shutil

    if not STACKING_DIR.exists():
        return {"message": "没有需要清理的文件"}

    # 统计文件数量
    files_count = sum(1 for _ in STACKING_DIR.rglob("*") if _.is_file())

    # 删除目录
    shutil.rmtree(STACKING_DIR)

    return {
        "message": f"已清理 Stacking 模型文件",
        "files_removed": files_count,
    }
