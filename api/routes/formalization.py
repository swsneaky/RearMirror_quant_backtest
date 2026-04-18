"""
模型固化与晋升 API

端点:
  POST /api/models/register   -- 注册模型
  POST /api/models/promote    -- 晋升模型
  GET  /api/models/registry   -- 获取模型注册表
  GET  /api/models/{model_id} -- 获取单个模型详情
  DELETE /api/models/{model_id} -- 删除模型
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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
)

router = APIRouter(prefix="/api/models", tags=["formalization"])


# ================================================================
# Request/Response Models
# ================================================================
class RegisterModelRequest(BaseModel):
    """注册模型请求"""
    model_type: str = Field(..., description="模型类型: xgboost, lightgbm, stacking, etc.")
    model_path: str = Field(..., description="模型文件路径")
    metrics: dict[str, Any] = Field(..., description="模型评估指标")
    feature_set_id: Optional[str] = Field(None, description="特征集 ID")
    label_set_id: Optional[str] = Field(None, description="标签集 ID")
    training_config: Optional[dict[str, Any]] = Field(None, description="训练配置")
    version: str = Field("1.0.0", description="模型版本")
    description: str = Field("", description="模型描述")
    tags: list[str] = Field(default_factory=list, description="标签列表")
    copy_model: bool = Field(True, description="是否复制模型文件")


class RegisterModelResponse(BaseModel):
    """注册模型响应"""
    success: bool
    model_id: str
    message: str


class PromoteModelRequest(BaseModel):
    """晋升模型请求"""
    model_id: str = Field(..., description="模型 ID")
    force: bool = Field(False, description="是否强制晋升")


class CheckResultResponse(BaseModel):
    """检查结果"""
    name: str
    result: str
    message: str
    value: Optional[Any] = None
    threshold: Optional[Any] = None


class PromoteModelResponse(BaseModel):
    """晋升模型响应"""
    success: bool
    model_id: str
    checks: list[CheckResultResponse]
    message: str
    promoted_at: Optional[str] = None
    deprecated_models: list[str] = []


class ModelMetadataResponse(BaseModel):
    """模型元数据响应"""
    model_id: str
    model_type: str
    version: str
    status: str
    created_at: str
    updated_at: str
    metrics: dict[str, Any]
    training_config: dict[str, Any]
    feature_set_id: Optional[str]
    label_set_id: Optional[str]
    model_path: str
    metadata_path: str
    description: str
    tags: list[str]
    promotion_history: list[dict[str, Any]]


class RegistryResponse(BaseModel):
    """注册表响应"""
    models: list[ModelMetadataResponse]
    total_count: int
    status_counts: dict[str, int]


class RegisterFromExperimentRequest(BaseModel):
    """从实验注册模型请求"""
    experiment_id: str = Field(..., description="实验 ID")
    description: str = Field("", description="模型描述")
    tags: list[str] = Field(default_factory=list, description="标签列表")


# ================================================================
# Helper Functions
# ================================================================
def _metadata_to_response(metadata: ModelMetadata) -> ModelMetadataResponse:
    """将 ModelMetadata 转换为响应模型"""
    return ModelMetadataResponse(
        model_id=metadata.model_id,
        model_type=metadata.model_type,
        version=metadata.version,
        status=metadata.status,
        created_at=metadata.created_at,
        updated_at=metadata.updated_at,
        metrics=metadata.metrics,
        training_config=metadata.training_config,
        feature_set_id=metadata.feature_set_id,
        label_set_id=metadata.label_set_id,
        model_path=metadata.model_path,
        metadata_path=metadata.metadata_path,
        description=metadata.description,
        tags=metadata.tags,
        promotion_history=metadata.promotion_history,
    )


# ================================================================
# API Endpoints
# ================================================================
@router.post("/register", response_model=RegisterModelResponse)
async def register_model(request: RegisterModelRequest):
    """
    注册模型

    将训练好的模型注册到模型注册表
    """
    try:
        registry = ModelRegistry.from_config()
        model_id = registry.register(
            model_type=request.model_type,
            model_path=request.model_path,
            metrics=request.metrics,
            feature_set_id=request.feature_set_id,
            label_set_id=request.label_set_id,
            training_config=request.training_config or {},
            version=request.version,
            description=request.description,
            tags=request.tags,
            copy_model=request.copy_model,
        )

        return RegisterModelResponse(
            success=True,
            model_id=model_id,
            message=f"模型已注册: {model_id}",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"注册失败: {exc}")


@router.post("/register/experiment", response_model=RegisterModelResponse)
async def register_from_experiment(request: RegisterFromExperimentRequest):
    """
    从实验结果注册模型

    从已完成的实验中提取模型并注册
    """
    try:
        model_id = register_model_from_experiment(
            experiment_id=request.experiment_id,
            description=request.description,
            tags=request.tags,
        )

        if model_id is None:
            raise HTTPException(status_code=404, detail="实验不存在或未找到模型")

        return RegisterModelResponse(
            success=True,
            model_id=model_id,
            message=f"模型已从实验注册: {model_id}",
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"注册失败: {exc}")


@router.post("/promote", response_model=PromoteModelResponse)
async def promote_model(request: PromoteModelRequest):
    """
    晋升模型

    执行晋升检查并将模型标记为正式模型
    """
    try:
        promoter = ModelPromoter.from_config()
        result = promoter.promote(request.model_id, force=request.force)

        return PromoteModelResponse(
            success=result.success,
            model_id=result.model_id,
            checks=[
                CheckResultResponse(
                    name=c.name,
                    result=c.result,
                    message=c.message,
                    value=c.value,
                    threshold=c.threshold,
                )
                for c in result.checks
            ],
            message=result.message,
            promoted_at=result.promoted_at,
            deprecated_models=result.deprecated_models,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"晋升失败: {exc}")


@router.get("/registry", response_model=RegistryResponse)
async def get_registry(
    status: Optional[str] = None,
    model_type: Optional[str] = None,
    limit: int = 100,
):
    """
    获取模型注册表

    返回所有已注册的模型列表
    """
    try:
        registry = ModelRegistry.from_config()
        models = registry.list(status=status, model_type=model_type, limit=limit)

        # 统计状态
        status_counts = {}
        for status_val in ModelStatus:
            status_models = registry.list(status=status_val.value, limit=1000)
            status_counts[status_val.value] = len(status_models)

        return RegistryResponse(
            models=[_metadata_to_response(m) for m in models],
            total_count=len(models),
            status_counts=status_counts,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"获取注册表失败: {exc}")


@router.get("/{model_id}", response_model=ModelMetadataResponse)
async def get_model(model_id: str):
    """
    获取单个模型详情

    返回指定模型的元数据
    """
    try:
        registry = ModelRegistry.from_config()
        metadata = registry.get(model_id)

        if metadata is None:
            raise HTTPException(status_code=404, detail=f"模型不存在: {model_id}")

        return _metadata_to_response(metadata)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"获取模型失败: {exc}")


@router.delete("/{model_id}")
async def delete_model(model_id: str):
    """
    删除模型

    从注册表中删除指定模型
    """
    try:
        registry = ModelRegistry.from_config()
        success = registry.delete(model_id)

        if not success:
            raise HTTPException(status_code=404, detail=f"模型不存在: {model_id}")

        return {"success": True, "message": f"模型已删除: {model_id}"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"删除失败: {exc}")


@router.post("/{model_id}/validate")
async def validate_model(model_id: str):
    """
    验证模型

    将模型状态更新为 validated
    """
    try:
        registry = ModelRegistry.from_config()
        success = registry.validate(model_id)

        if not success:
            raise HTTPException(status_code=400, detail="验证失败，模型不存在")

        return {"success": True, "message": f"模型已验证: {model_id}"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"验证失败: {exc}")


@router.post("/{model_id}/deprecate")
async def deprecate_model(model_id: str, reason: str = ""):
    """
    废弃模型

    将模型状态更新为 deprecated
    """
    try:
        registry = ModelRegistry.from_config()
        success = registry.deprecate(model_id, reason=reason)

        if not success:
            raise HTTPException(status_code=400, detail="废弃失败，模型不存在")

        return {"success": True, "message": f"模型已废弃: {model_id}"}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"废弃失败: {exc}")


@router.get("/promoted/latest")
async def get_latest_promoted(model_type: Optional[str] = None):
    """
    获取最新晋升的模型

    返回指定类型的最新正式模型
    """
    try:
        registry = ModelRegistry.from_config()
        metadata = registry.get_latest_promoted(model_type=model_type)

        if metadata is None:
            return {"success": False, "message": "没有找到已晋升的模型"}

        return {
            "success": True,
            "model": _metadata_to_response(metadata),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"获取失败: {exc}")


# ================================================================
# 晋升条件配置
# ================================================================
@router.get("/promotion/criteria")
async def get_promotion_criteria():
    """
    获取晋升条件配置

    返回当前的晋升准入条件
    """
    from src.formalization.model_promoter import DEFAULT_PROMOTION_CRITERIA

    return {
        "criteria": DEFAULT_PROMOTION_CRITERIA,
        "description": "默认晋升准入条件",
    }
