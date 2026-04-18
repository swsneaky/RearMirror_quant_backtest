"""
回测结果 API

端点:
  GET  /api/backtest/results   -- 获取最近的回测结果
  GET  /api/backtest/iterations -- 获取所有迭代结果摘要
  POST /api/backtest/run       -- 触发回测任务 (异步)
  GET  /api/backtest/nav       -- 获取 NAV 曲线数据
"""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pathlib import Path
import json
from typing import Optional
from pydantic import BaseModel
import pandas as pd

router = APIRouter(prefix="/api/backtest", tags=["backtest"])

RESULTS_DIR = Path("data/results/results")
ITERATIONS_DIR = Path("data/results/iterations")


class BacktestMetrics(BaseModel):
    """回测指标"""
    ann_return: float
    ann_excess_return: float
    ann_volatility: float
    tracking_error: float
    sharpe_ratio: float
    information_ratio: float
    max_drawdown: float
    excess_max_drawdown: float
    avg_turnover: float
    avg_cost_per_period: float


class BacktestResultsResponse(BaseModel):
    """回测结果响应"""
    metrics: Optional[BacktestMetrics] = None
    has_results: bool
    results_path: str


class IterationSummary(BaseModel):
    """迭代摘要"""
    iteration_id: str
    date: str
    stage: str
    conclusion: str
    metrics: dict
    data_scale: dict
    recommendation: str


class IterationsResponse(BaseModel):
    """迭代列表响应"""
    iterations: list[IterationSummary]
    total: int


class BacktestRunRequest(BaseModel):
    """回测运行请求"""
    notes: str = ""


class BacktestRunResponse(BaseModel):
    """回测运行响应"""
    success: bool
    task_id: str
    message: str


class NavDataPoint(BaseModel):
    """NAV 数据点"""
    date: str
    strategy_nav: float
    benchmark_nav: float
    excess_nav: Optional[float] = None


class NavResponse(BaseModel):
    """NAV 曲线响应"""
    has_data: bool
    data: list[NavDataPoint]
    message: Optional[str] = None


# ================================================================
# 辅助函数
# ================================================================
def _run_backtest_task(task_id: str):
    """后台执行回测任务"""
    from src.tasking.runner import run_task
    from src.tasking.store import TaskStore
    from src.tasking.models import TaskStatus

    store = TaskStore()
    task = store.get(task_id)
    if task is None:
        return

    run_task(
        task.config_snapshot_path,
        task.output_dir,
        store._db_path,
        task_id,
    )


# ================================================================
# 端点实现
# ================================================================
@router.post("/run", response_model=BacktestRunResponse)
async def run_backtest(
    request: BacktestRunRequest,
    background_tasks: BackgroundTasks,
):
    """
    触发回测任务 (异步执行)

    使用 BackgroundTasks 在后台运行回测，立即返回任务 ID。
    """
    from src.tasking.manager import TaskManager
    from src.tasking.store import TaskStore

    try:
        manager = TaskManager(store=TaskStore())
        record = manager.submit(
            steps=["backtest"],
            notes=request.notes or "API 触发回测",
            submit_source="api",
        )

        # 启动后台执行器 (如果未启动)
        from src.tasking.executor import TaskExecutor
        executor = TaskExecutor.get_instance() if hasattr(TaskExecutor, "get_instance") else None
        if executor is None:
            # 如果没有全局执行器，直接在后台运行
            background_tasks.add_task(_run_backtest_task, record.task_id)

        return BacktestRunResponse(
            success=True,
            task_id=record.task_id,
            message=f"回测任务 {record.task_id} 已创建",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建回测任务失败: {str(e)}")


@router.get("/nav", response_model=NavResponse)
async def get_nav_curve():
    """
    获取 NAV 曲线数据

    从 data/results/results/nav_daily.parquet 读取 NAV 曲线。
    返回日期数组、策略 NAV、基准 NAV。
    """
    nav_path = RESULTS_DIR / "nav_daily.parquet"

    if not nav_path.exists():
        return NavResponse(
            has_data=False,
            data=[],
            message="NAV 数据文件不存在，请先运行回测",
        )

    try:
        df = pd.read_parquet(nav_path)

        # 确保 date 列为字符串格式
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")

        data_points = []
        for _, row in df.iterrows():
            point = NavDataPoint(
                date=row["date"],
                strategy_nav=float(row.get("nav", 1.0)),
                benchmark_nav=float(row.get("bench_nav", 1.0)),
                excess_nav=float(row.get("excess_nav")) if "excess_nav" in row and pd.notna(row.get("excess_nav")) else None,
            )
            data_points.append(point)

        return NavResponse(
            has_data=True,
            data=data_points,
            message=f"共 {len(data_points)} 个数据点",
        )
    except Exception as e:
        return NavResponse(
            has_data=False,
            data=[],
            message=f"读取 NAV 数据失败: {str(e)}",
        )


@router.get("/results", response_model=BacktestResultsResponse)
async def get_backtest_results():
    """
    获取最近的回测结果

    返回最新的 metrics_summary.json 内容
    """
    metrics_path = RESULTS_DIR / "metrics_summary.json"

    if not metrics_path.exists():
        return BacktestResultsResponse(
            metrics=None,
            has_results=False,
            results_path=str(RESULTS_DIR)
        )

    try:
        with open(metrics_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return BacktestResultsResponse(
            metrics=BacktestMetrics(**data),
            has_results=True,
            results_path=str(RESULTS_DIR)
        )
    except Exception as e:
        return BacktestResultsResponse(
            metrics=None,
            has_results=False,
            results_path=str(RESULTS_DIR)
        )


@router.get("/iterations", response_model=IterationsResponse)
async def get_iterations():
    """
    获取所有迭代结果摘要

    扫描 iterations 目录下的所有迭代
    """
    iterations = []

    if not ITERATIONS_DIR.exists():
        return IterationsResponse(iterations=[], total=0)

    for iter_dir in sorted(ITERATIONS_DIR.iterdir(), reverse=True):
        if not iter_dir.is_dir():
            continue

        summary_path = iter_dir / "iteration_result_summary.json"
        if summary_path.exists():
            try:
                with open(summary_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                iterations.append(IterationSummary(
                    iteration_id=data.get("iteration_id", iter_dir.name),
                    date=data.get("date", ""),
                    stage=data.get("stage", ""),
                    conclusion=data.get("conclusion", ""),
                    metrics=data.get("metrics", {}),
                    data_scale=data.get("data_scale", {}),
                    recommendation=data.get("recommendation", "")
                ))
            except Exception:
                continue

    return IterationsResponse(
        iterations=iterations,
        total=len(iterations)
    )
