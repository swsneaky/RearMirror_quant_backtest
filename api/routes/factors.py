"""
因子分析 API

端点:
  GET /api/factors/summary      -- 获取 ICIR 汇总表
  GET /api/factors/ic-series    -- 获取 IC 时间序列
  GET /api/factors/correlation  -- 获取因子相关性矩阵
  POST /api/factors/run         -- 触发 IC 分析计算
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
import pandas as pd
from pathlib import Path

from src.config_loader import load_config
from src.data_layer.db import get_connection, cursor

router = APIRouter(prefix="/api/factors", tags=["factors"])


# ================================================================
# 响应模型
# ================================================================

class FactorSummaryItem(BaseModel):
    """单个因子的 ICIR 汇总"""
    factor_name: str
    ic_mean: float
    ic_std: float
    icir: float
    pos_ratio: float


class FactorSummaryResponse(BaseModel):
    """ICIR 汇总表响应"""
    analysis_id: Optional[str] = None
    feature_set_id: Optional[str] = None
    factors: list[FactorSummaryItem]
    total: int
    has_data: bool


class ICSeriesPoint(BaseModel):
    """IC 时间序列单点"""
    date: str
    factor_name: str
    ic_value: float


class ICSeriesResponse(BaseModel):
    """IC 时间序列响应"""
    analysis_id: Optional[str] = None
    series: list[ICSeriesPoint]
    dates: list[str]  # 所有日期列表
    factors: list[str]  # 所有因子列表
    total: int
    has_data: bool


class CorrelationResponse(BaseModel):
    """因子相关性矩阵响应"""
    factors: list[str]
    matrix: list[list[float]]  # 二维数组
    has_data: bool


class RunAnalysisRequest(BaseModel):
    """触发 IC 分析请求"""
    feature_set_id: Optional[str] = None
    label_set_id: Optional[str] = None


class RunAnalysisResponse(BaseModel):
    """触发 IC 分析响应"""
    status: str
    message: str
    analysis_id: Optional[str] = None


# ================================================================
# 辅助函数
# ================================================================

def _get_cfg() -> dict:
    """加载配置"""
    return load_config()


def _get_latest_analysis_id() -> Optional[str]:
    """获取最新的 analysis_id"""
    cfg = _get_cfg()
    try:
        with cursor(cfg) as cur:
            cur.execute("""
                SELECT analysis_id FROM factor_analysis_summary
                ORDER BY created_at DESC LIMIT 1
            """)
            row = cur.fetchone()
            if row:
                return row[0]
    except Exception:
        pass
    return None


# ================================================================
# 端点实现
# ================================================================

@router.get("/summary", response_model=FactorSummaryResponse)
async def get_factor_summary(analysis_id: Optional[str] = None):
    """
    获取 ICIR 汇总表

    从 factor_analysis_summary 表读取因子 IC 分析汇总数据。
    如果不指定 analysis_id，返回最新一次分析的结果。
    """
    cfg = _get_cfg()
    target_id = analysis_id or _get_latest_analysis_id()

    if not target_id:
        return FactorSummaryResponse(
            factors=[],
            total=0,
            has_data=False
        )

    try:
        with cursor(cfg) as cur:
            # 获取 feature_set_id
            cur.execute("""
                SELECT DISTINCT feature_set_id FROM factor_analysis_summary
                WHERE analysis_id = ?
            """, [target_id])
            row = cur.fetchone()
            feature_set_id = row[0] if row else None

            # 获取因子汇总
            cur.execute("""
                SELECT factor_name, ic_mean, ic_std, icir, pos_ratio
                FROM factor_analysis_summary
                WHERE analysis_id = ?
                ORDER BY icir DESC
            """, [target_id])
            rows = cur.fetchall()

            factors = [
                FactorSummaryItem(
                    factor_name=r[0],
                    ic_mean=r[1] or 0.0,
                    ic_std=r[2] or 0.0,
                    icir=r[3] or 0.0,
                    pos_ratio=r[4] or 0.0
                )
                for r in rows
            ]

            return FactorSummaryResponse(
                analysis_id=target_id,
                feature_set_id=feature_set_id,
                factors=factors,
                total=len(factors),
                has_data=len(factors) > 0
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


@router.get("/ic-series", response_model=ICSeriesResponse)
async def get_ic_series(
    analysis_id: Optional[str] = None,
    factor_name: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
):
    """
    获取 IC 时间序列

    从 factor_ic_series 表读取 IC 时间序列数据。
    支持按因子名、日期范围过滤。
    """
    cfg = _get_cfg()
    target_id = analysis_id or _get_latest_analysis_id()

    if not target_id:
        return ICSeriesResponse(
            series=[],
            dates=[],
            factors=[],
            total=0,
            has_data=False
        )

    try:
        with cursor(cfg) as cur:
            # 构建查询
            sql = """
                SELECT date, factor_name, ic_value
                FROM factor_ic_series
                WHERE analysis_id = ?
            """
            params = [target_id]

            if factor_name:
                sql += " AND factor_name = ?"
                params.append(factor_name)

            if start_date:
                sql += " AND date >= ?"
                params.append(start_date)

            if end_date:
                sql += " AND date <= ?"
                params.append(end_date)

            sql += " ORDER BY date, factor_name"

            cur.execute(sql, params)
            rows = cur.fetchall()

            # 收集唯一日期和因子
            dates_set = set()
            factors_set = set()
            series = []

            for r in rows:
                date_str = r[0]
                fn = r[1]
                ic_val = r[2]

                dates_set.add(date_str)
                factors_set.add(fn)

                if ic_val is not None:
                    series.append(ICSeriesPoint(
                        date=date_str,
                        factor_name=fn,
                        ic_value=ic_val
                    ))

            return ICSeriesResponse(
                analysis_id=target_id,
                series=series,
                dates=sorted(list(dates_set)),
                factors=sorted(list(factors_set)),
                total=len(series),
                has_data=len(series) > 0
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")


@router.get("/correlation", response_model=CorrelationResponse)
async def get_factor_correlation(analysis_id: Optional[str] = None):
    """
    获取因子相关性矩阵

    基于 IC 时间序列计算因子间的 Pearson 相关系数矩阵。
    """
    cfg = _get_cfg()
    target_id = analysis_id or _get_latest_analysis_id()

    if not target_id:
        return CorrelationResponse(
            factors=[],
            matrix=[],
            has_data=False
        )

    try:
        with cursor(cfg) as cur:
            # 读取 IC 时间序列并 pivot 为宽表
            cur.execute("""
                SELECT date, factor_name, ic_value
                FROM factor_ic_series
                WHERE analysis_id = ?
            """, [target_id])
            rows = cur.fetchall()

            if not rows:
                return CorrelationResponse(
                    factors=[],
                    matrix=[],
                    has_data=False
                )

            # 构建 DataFrame
            data = []
            for r in rows:
                data.append({
                    "date": r[0],
                    "factor_name": r[1],
                    "ic_value": r[2]
                })

            df = pd.DataFrame(data)
            ic_wide = df.pivot(index="date", columns="factor_name", values="ic_value")

            # 计算相关性矩阵
            corr_matrix = ic_wide.corr(method="pearson")

            # 填充 NaN 为 0
            corr_matrix = corr_matrix.fillna(0)

            factors = list(corr_matrix.columns)
            matrix = corr_matrix.values.tolist()

            return CorrelationResponse(
                factors=factors,
                matrix=matrix,
                has_data=True
            )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"计算相关性矩阵失败: {str(e)}")


@router.post("/run", response_model=RunAnalysisResponse)
async def run_ic_analysis(
    request: RunAnalysisRequest,
    background_tasks: BackgroundTasks
):
    """
    触发 IC 分析计算

    后台运行 IC 分析，计算因子 IC、ICIR、IC Decay、相关性矩阵。
    使用 src/factors/ic_analysis.py 中的 run_ic_analysis 函数。
    """
    from src.factors.ic_analysis import run_ic_analysis
    from src.data_layer.asset_id import make_config_hash

    cfg = _get_cfg()

    # 生成 analysis_id
    feat_cfg = cfg.get("features", {})
    analysis_id = f"ic__{make_config_hash(feat_cfg)[:12]}"

    try:
        # 在后台执行 IC 分析
        def run_analysis():
            try:
                run_ic_analysis(
                    cfg,
                    feature_set_id=request.feature_set_id,
                    label_set_id=request.label_set_id
                )
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"IC 分析失败: {e}")

        background_tasks.add_task(run_analysis)

        return RunAnalysisResponse(
            status="started",
            message="IC 分析已启动，请在后台运行完成后查询结果",
            analysis_id=analysis_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"启动 IC 分析失败: {str(e)}")
