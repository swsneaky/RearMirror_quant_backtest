"""
模型固化与晋升模块

职责:
  - ModelRegistry: 模型版本管理和注册
  - ModelPromoter: 模型晋升流程和准入条件检查

产物格式:
  - model_metadata.json: 模型元数据

API 端点:
  - POST /api/models/register -- 注册模型
  - POST /api/models/promote  -- 晋升模型
  - GET  /api/models/registry -- 获取模型注册表
"""
from src.formalization.model_registry import ModelRegistry, ModelMetadata
from src.formalization.model_promoter import ModelPromoter, PromotionResult

__all__ = [
    "ModelRegistry",
    "ModelMetadata",
    "ModelPromoter",
    "PromotionResult",
]
