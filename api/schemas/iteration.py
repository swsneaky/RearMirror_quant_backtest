"""
迭代结果 JSON Schema (Pydantic models)

定义迭代结果 API 的请求/响应模型，符合 result_reporting.md 规范
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field
from datetime import date as date_type


class IterationMetrics(BaseModel):
    """迭代指标"""
    ann_return: Optional[float] = None
    ann_excess_return: Optional[float] = None
    ann_volatility: Optional[float] = None
    information_ratio: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    excess_max_drawdown: Optional[float] = None
    avg_turnover: Optional[float] = None
    icir_mean: Optional[float] = None
    median_abs_icir: Optional[float] = None


class DataScale(BaseModel):
    """数据规模"""
    feature_count: Optional[int] = None
    dataset_rows: Optional[int] = None
    prediction_records: Optional[int] = None
    wfa_folds: Optional[int] = None


class Artifacts(BaseModel):
    """产物清单"""
    predictions: Optional[str] = None
    holdings: Optional[str] = None
    nav_daily: Optional[str] = None
    metrics: Optional[str] = None
    brief: Optional[str] = None
    config_snapshot: Optional[str] = None


class IterationResultSummary(BaseModel):
    """迭代结果摘要 - iteration_result_summary.json 格式"""
    iteration_id: str
    date: str
    stage: str
    feature_set_id: Optional[str] = None
    label_set_id: Optional[str] = None
    runtime_mode: Optional[str] = None
    conclusion: str
    metrics: IterationMetrics = Field(default_factory=IterationMetrics)
    data_scale: DataScale = Field(default_factory=DataScale)
    recommendation: str
    recommendation_reason: Optional[str] = None
    premises: list[str] = Field(default_factory=list)
    artifacts: Artifacts = Field(default_factory=Artifacts)
    hpo_study_name: Optional[str] = None


class IterationCreateRequest(BaseModel):
    """创建迭代请求"""
    iteration_id: Optional[str] = None  # 可选，自动生成
    date: Optional[str] = None  # 可选，默认今天
    stage: str
    feature_set_id: Optional[str] = None
    label_set_id: Optional[str] = None
    runtime_mode: Optional[str] = None
    conclusion: str
    metrics: Optional[dict] = None
    data_scale: Optional[dict] = None
    recommendation: str
    recommendation_reason: Optional[str] = None
    premises: Optional[list[str]] = None
    artifacts: Optional[dict] = None
    hpo_study_name: Optional[str] = None


class IterationCreateResponse(BaseModel):
    """创建迭代响应"""
    iteration_id: str
    json_path: str
    brief_path: str
    message: str


class IterationListItem(BaseModel):
    """迭代列表项"""
    iteration_id: str
    date: str
    stage: str
    conclusion: str
    recommendation: str


class IterationListResponse(BaseModel):
    """迭代列表响应"""
    iterations: list[IterationListItem]
    total: int


class IterationDetailResponse(BaseModel):
    """迭代详情响应"""
    iteration_id: str
    date: str
    stage: str
    feature_set_id: Optional[str] = None
    label_set_id: Optional[str] = None
    runtime_mode: Optional[str] = None
    conclusion: str
    metrics: dict
    data_scale: dict
    recommendation: str
    recommendation_reason: Optional[str] = None
    premises: list[str]
    artifacts: dict
    hpo_study_name: Optional[str] = None
    brief_content: Optional[str] = None


class ArtifactsResponse(BaseModel):
    """产物清单响应"""
    iteration_id: str
    artifacts: dict
    all_exist: bool
    missing: list[str]


class HPOStudyReport(BaseModel):
    """HPO 研究报告"""
    study_name: str
    model_name: str
    objective_metric: str
    direction: str
    n_trials: int
    best_trial: Optional[int] = None
    best_value: Optional[float] = None
    best_params: dict = Field(default_factory=dict)
    timestamp: Optional[str] = None
    related_iteration: Optional[str] = None
