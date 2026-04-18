"""
配置管理 API

端点:
  GET  /api/config              -- 获取完整配置
  GET  /api/config/etl          -- 获取 ETL 配置块
  PUT  /api/config/etl          -- 更新 ETL 配置 (持久化到 base_config.yaml)
  GET  /api/config/features     -- 获取特征配置块
  PUT  /api/config/features     -- 更新特征配置
  GET  /api/config/cross_section -- 获取截面处理配置
  PUT  /api/config/cross_section -- 更新截面处理配置
  GET  /api/config/options      -- 获取所有可选项 (指数列表、因子组列表等)
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from src.config_loader import load_config

router = APIRouter(prefix="/api/config", tags=["config"])

CONFIG_PATH = Path("configs/base_config.yaml")


# ================================================================
# 响应模型
# ================================================================
class ETLConfigResponse(BaseModel):
    """ETL 配置响应"""
    index_name: str
    start_date: str
    end_date: str
    max_stocks: int
    update_mode: str
    # 只读辅助
    available_indices: list[str]


class ETLConfigUpdate(BaseModel):
    """ETL 配置更新请求"""
    index_name: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    max_stocks: Optional[int] = None
    update_mode: Optional[str] = None

    @field_validator('start_date', 'end_date')
    @classmethod
    def validate_date(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', v):
            raise ValueError(f'日期格式必须是 YYYY-MM-DD: {v}')
        try:
            datetime.strptime(v, '%Y-%m-%d')
        except ValueError as e:
            raise ValueError(f'无效日期: {v}') from e
        return v

    @field_validator('max_stocks')
    @classmethod
    def validate_max_stocks(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError('max_stocks 必须为非负整数')
        return v

    @field_validator('update_mode')
    @classmethod
    def validate_update_mode(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ('incremental', 'full'):
            raise ValueError('update_mode 必须是 incremental 或 full')
        return v


class FeaturesConfigResponse(BaseModel):
    """特征配置响应"""
    active_factors: list[str]
    excluded_features: list[str]
    # 只读辅助
    available_factor_groups: list[str]


class FeaturesConfigUpdate(BaseModel):
    """特征配置更新请求"""
    active_factors: Optional[list[str]] = None
    excluded_features: Optional[list[str]] = None


class CrossSectionConfigResponse(BaseModel):
    """截面处理配置响应"""
    mad_multiplier: float
    min_industry_stocks: int
    zscore_eps: float


class CrossSectionConfigUpdate(BaseModel):
    """截面处理配置更新请求"""
    mad_multiplier: Optional[float] = None
    min_industry_stocks: Optional[int] = None
    zscore_eps: Optional[float] = None

    @field_validator('mad_multiplier')
    @classmethod
    def validate_mad_multiplier(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v <= 0:
            raise ValueError('mad_multiplier 必须为正数')
        return v

    @field_validator('min_industry_stocks')
    @classmethod
    def validate_min_industry_stocks(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 1:
            raise ValueError('min_industry_stocks 必须为正整数')
        return v


class ConfigOptionsResponse(BaseModel):
    """所有可选项 (前端下拉框数据源)"""
    available_indices: list[str]
    available_factor_groups: list[str]
    available_models: list[str]
    objective_metrics: list[str]
    meta_learner_types: list[str]


class FullConfigResponse(BaseModel):
    """完整配置响应"""
    etl: dict
    features: dict
    cross_section: dict
    model: dict


# ================================================================
# 可选项定义 (硬编码，后续可扩展为动态)
# ================================================================
AVAILABLE_INDICES = ["zz500", "hs300", "zz1000", "all"]
AVAILABLE_FACTOR_GROUPS = ["kline", "rolling", "rolling_ext", "technical", "turnover", "valuation"]
AVAILABLE_MODELS = ["lightgbm", "xgboost", "random_forest"]
OBJECTIVE_METRICS = ["sharpe_ratio", "ic_mean", "icir", "annual_return"]
META_LEARNER_TYPES = ["weight_averaging", "linear"]


# ================================================================
# 辅助函数
# ================================================================
def _save_config_section(section: str, data: dict) -> None:
    """保存配置块到 YAML 文件"""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    if section not in cfg:
        cfg[section] = {}

    cfg[section] = {**cfg[section], **data}

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


# ================================================================
# 端点实现
# ================================================================
@router.get("", response_model=FullConfigResponse)
async def get_full_config():
    """获取完整配置"""
    cfg = load_config()
    return FullConfigResponse(
        etl=cfg.get("etl", {}),
        features=cfg.get("features", {}),
        cross_section=cfg.get("cross_section", {}),
        model=cfg.get("model", {}),
    )


@router.get("/etl", response_model=ETLConfigResponse)
async def get_etl_config():
    """获取 ETL 配置块"""
    cfg = load_config()
    etl = cfg.get("etl", {})
    return ETLConfigResponse(
        index_name=etl.get("index_name", "zz500"),
        start_date=etl.get("start_date", "2016-01-01"),
        end_date=etl.get("end_date", "2026-03-29"),
        max_stocks=etl.get("max_stocks", 0),
        update_mode=etl.get("update_mode", "incremental"),
        available_indices=AVAILABLE_INDICES,
    )


@router.put("/etl")
async def update_etl_config(data: ETLConfigUpdate):
    """更新 ETL 配置 (持久化到 base_config.yaml)"""
    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="没有要更新的配置项")

    # 验证 index_name
    if "index_name" in update_data and update_data["index_name"] not in AVAILABLE_INDICES:
        raise HTTPException(
            status_code=400,
            detail=f"无效的 index_name: {update_data['index_name']}。可选: {AVAILABLE_INDICES}"
        )

    _save_config_section("etl", update_data)

    return {"success": True, "message": "ETL 配置已保存", "updated_fields": list(update_data.keys())}


@router.get("/features", response_model=FeaturesConfigResponse)
async def get_features_config():
    """获取特征配置块"""
    cfg = load_config()
    features = cfg.get("features", {})
    active_factors = features.get("active_factors", [])

    return FeaturesConfigResponse(
        active_factors=active_factors,
        excluded_features=features.get("excluded_features", []),
        available_factor_groups=AVAILABLE_FACTOR_GROUPS,
    )


@router.put("/features")
async def update_features_config(data: FeaturesConfigUpdate):
    """更新特征配置 (持久化到 base_config.yaml)"""
    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="没有要更新的配置项")

    # 验证 active_factors
    if "active_factors" in update_data:
        invalid = [f for f in update_data["active_factors"] if f not in AVAILABLE_FACTOR_GROUPS]
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"无效的因子组: {invalid}。可选: {AVAILABLE_FACTOR_GROUPS}"
            )

    _save_config_section("features", update_data)

    return {"success": True, "message": "特征配置已保存", "updated_fields": list(update_data.keys())}


@router.get("/cross_section", response_model=CrossSectionConfigResponse)
async def get_cross_section_config():
    """获取截面处理配置块"""
    cfg = load_config()
    cs = cfg.get("cross_section", {})
    return CrossSectionConfigResponse(
        mad_multiplier=cs.get("mad_multiplier", 3.148),
        min_industry_stocks=cs.get("min_industry_stocks", 5),
        zscore_eps=cs.get("zscore_eps", 1.0e-8),
    )


@router.put("/cross_section")
async def update_cross_section_config(data: CrossSectionConfigUpdate):
    """更新截面处理配置 (持久化到 base_config.yaml)"""
    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="没有要更新的配置项")

    _save_config_section("cross_section", update_data)

    return {"success": True, "message": "截面处理配置已保存", "updated_fields": list(update_data.keys())}


@router.get("/options", response_model=ConfigOptionsResponse)
async def get_config_options():
    """获取所有可选项 (前端下拉框数据源)"""
    return ConfigOptionsResponse(
        available_indices=AVAILABLE_INDICES,
        available_factor_groups=AVAILABLE_FACTOR_GROUPS,
        available_models=AVAILABLE_MODELS,
        objective_metrics=OBJECTIVE_METRICS,
        meta_learner_types=META_LEARNER_TYPES,
    )


# ================================================================
# Model Config
# ================================================================
class ModelConfigResponse(BaseModel):
    """模型配置响应"""
    active: str
    lightgbm: dict
    xgboost: dict
    random_forest: dict


class ModelConfigUpdate(BaseModel):
    """模型配置更新请求"""
    active: Optional[str] = None
    lightgbm: Optional[dict] = None
    xgboost: Optional[dict] = None
    random_forest: Optional[dict] = None

    @field_validator('active')
    @classmethod
    def validate_active(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in AVAILABLE_MODELS:
            raise ValueError(f'无效的模型: {v}。可选: {AVAILABLE_MODELS}')
        return v


@router.get("/model", response_model=ModelConfigResponse)
async def get_model_config():
    """获取模型配置"""
    cfg = load_config()
    model = cfg.get("model", {})
    return ModelConfigResponse(
        active=model.get("active", "lightgbm"),
        lightgbm=model.get("lightgbm", {}),
        xgboost=model.get("xgboost", {}),
        random_forest=model.get("random_forest", {}),
    )


@router.put("/model")
async def update_model_config(data: ModelConfigUpdate):
    """更新模型配置"""
    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="没有要更新的配置项")

    _save_config_section("model", update_data)
    return {"success": True, "message": "模型配置已保存", "updated_fields": list(update_data.keys())}


# ================================================================
# Backtest Config
# ================================================================
class BacktestConfigResponse(BaseModel):
    """回测配置响应"""
    train_window: int
    gap: int
    test_step: int
    top_k: int
    friction_cost: float
    limit_pct_threshold: float
    return_shap: bool


class BacktestConfigUpdate(BaseModel):
    """回测配置更新请求"""
    train_window: Optional[int] = None
    gap: Optional[int] = None
    test_step: Optional[int] = None
    top_k: Optional[int] = None
    friction_cost: Optional[float] = None
    limit_pct_threshold: Optional[float] = None
    return_shap: Optional[bool] = None

    @field_validator('train_window', 'gap', 'test_step', 'top_k')
    @classmethod
    def validate_positive_int(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 1:
            raise ValueError('必须为正整数')
        return v

    @field_validator('friction_cost')
    @classmethod
    def validate_friction_cost(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and (v < 0 or v > 0.1):
            raise ValueError('friction_cost 必须在 0-0.1 之间')
        return v


@router.get("/backtest", response_model=BacktestConfigResponse)
async def get_backtest_config():
    """获取回测配置"""
    cfg = load_config()
    bt = cfg.get("backtest", {})
    return BacktestConfigResponse(
        train_window=bt.get("train_window", 500),
        gap=bt.get("gap", 5),
        test_step=bt.get("test_step", 5),
        top_k=bt.get("top_k", 30),
        friction_cost=bt.get("friction_cost", 0.0004),
        limit_pct_threshold=bt.get("limit_pct_threshold", 9.8),
        return_shap=bt.get("return_shap", False),
    )


@router.put("/backtest")
async def update_backtest_config(data: BacktestConfigUpdate):
    """更新回测配置"""
    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="没有要更新的配置项")

    _save_config_section("backtest", update_data)
    return {"success": True, "message": "回测配置已保存", "updated_fields": list(update_data.keys())}


# ================================================================
# HPO Config
# ================================================================
OBJECTIVE_METRICS = ["sharpe_ratio", "ic_mean", "icir", "annual_return"]


class HPOConfigResponse(BaseModel):
    """HPO 配置响应"""
    enabled: bool
    n_trials: int
    objective_metric: str
    output_dir: str
    n_jobs: int
    timeout: Optional[int] = None
    resume: bool


class HPOConfigUpdate(BaseModel):
    """HPO 配置更新请求"""
    enabled: Optional[bool] = None
    n_trials: Optional[int] = None
    objective_metric: Optional[str] = None
    n_jobs: Optional[int] = None
    timeout: Optional[int] = None
    resume: Optional[bool] = None

    @field_validator('objective_metric')
    @classmethod
    def validate_objective_metric(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in OBJECTIVE_METRICS:
            raise ValueError(f'无效的优化目标: {v}。可选: {OBJECTIVE_METRICS}')
        return v


@router.get("/hpo", response_model=HPOConfigResponse)
async def get_hpo_config():
    """获取 HPO 配置"""
    cfg = load_config()
    hpo = cfg.get("hpo", {})
    return HPOConfigResponse(
        enabled=hpo.get("enabled", False),
        n_trials=hpo.get("n_trials", 50),
        objective_metric=hpo.get("objective_metric", "sharpe_ratio"),
        output_dir=hpo.get("output_dir", "data/results/hpo"),
        n_jobs=hpo.get("n_jobs", 1),
        timeout=hpo.get("timeout"),
        resume=hpo.get("resume", False),
    )


@router.put("/hpo")
async def update_hpo_config(data: HPOConfigUpdate):
    """更新 HPO 配置"""
    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="没有要更新的配置项")

    _save_config_section("hpo", update_data)
    return {"success": True, "message": "HPO 配置已保存", "updated_fields": list(update_data.keys())}


# ================================================================
# Stacking Config
# ================================================================
META_LEARNER_TYPES = ["weight_averaging", "linear"]


class StackingConfigResponse(BaseModel):
    """Stacking 配置响应"""
    enabled: bool
    base_learners: list[str]
    meta_learner: str
    validation_ratio: float
    cv_folds: int
    use_cv: bool


class StackingConfigUpdate(BaseModel):
    """Stacking 配置更新请求"""
    enabled: Optional[bool] = None
    base_learners: Optional[list[str]] = None
    meta_learner: Optional[str] = None
    validation_ratio: Optional[float] = None
    cv_folds: Optional[int] = None
    use_cv: Optional[bool] = None

    @field_validator('meta_learner')
    @classmethod
    def validate_meta_learner(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in META_LEARNER_TYPES:
            raise ValueError(f'无效的元学习器: {v}。可选: {META_LEARNER_TYPES}')
        return v

    @field_validator('base_learners')
    @classmethod
    def validate_base_learners(cls, v: Optional[list[str]]) -> Optional[list[str]]:
        if v is not None:
            invalid = [m for m in v if m not in AVAILABLE_MODELS]
            if invalid:
                raise ValueError(f'无效的基学习器: {invalid}。可选: {AVAILABLE_MODELS}')
        return v


@router.get("/stacking", response_model=StackingConfigResponse)
async def get_stacking_config():
    """获取 Stacking 配置"""
    cfg = load_config()
    stacking = cfg.get("stacking", {})
    return StackingConfigResponse(
        enabled=stacking.get("enabled", False),
        base_learners=stacking.get("base_learners", ["lightgbm", "xgboost"]),
        meta_learner=stacking.get("meta_learner", "weight_averaging"),
        validation_ratio=stacking.get("validation_ratio", 0.2),
        cv_folds=stacking.get("cv_folds", 5),
        use_cv=stacking.get("use_cv", True),
    )


@router.put("/stacking")
async def update_stacking_config(data: StackingConfigUpdate):
    """更新 Stacking 配置"""
    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="没有要更新的配置项")

    _save_config_section("stacking", update_data)
    return {"success": True, "message": "Stacking 配置已保存", "updated_fields": list(update_data.keys())}
