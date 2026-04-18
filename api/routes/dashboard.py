"""
Dashboard 聚合 API

端点:
  GET /api/dashboard/summary -- 获取聚合统计数据
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from src.config_loader import load_config

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


# ================================================================
# 响应模型
# ================================================================
class IterationsSummary(BaseModel):
    """迭代统计"""
    total: int


class HPOSummary(BaseModel):
    """HPO 统计"""
    status: str
    current_trial: int
    total_trials: int
    best_value: Optional[float] = None
    study_name: Optional[str] = None


class BacktestSummary(BaseModel):
    """回测统计"""
    has_results: bool
    sharpe_ratio: Optional[float] = None
    ann_return: Optional[float] = None
    max_drawdown: Optional[float] = None


class DataLayersSummary(BaseModel):
    """数据层统计"""
    total: int
    needs_update: int


class ModelsSummary(BaseModel):
    """模型统计"""
    total: int
    by_status: dict[str, int]


class TasksSummary(BaseModel):
    """任务统计"""
    total: int
    by_status: dict[str, int]


class StocksSummary(BaseModel):
    """股票统计"""
    total: int
    total_bars: int


class DashboardSummaryResponse(BaseModel):
    """Dashboard 聚合响应"""
    iterations: IterationsSummary
    hpo: HPOSummary
    backtest: BacktestSummary
    data_layers: DataLayersSummary
    models: ModelsSummary
    tasks: TasksSummary
    stocks: StocksSummary


# ================================================================
# 辅助函数
# ================================================================
def _get_iterations_count() -> int:
    """获取迭代总数"""
    iterations_dir = Path("data/results/iterations")
    if not iterations_dir.exists():
        return 0

    count = 0
    for item in iterations_dir.iterdir():
        if item.is_dir():
            count += 1
    return count


def _get_hpo_summary() -> dict:
    """获取 HPO 摘要"""
    import sqlite3

    hpo_dir = Path("data/results/hpo")

    if not hpo_dir.exists():
        return {
            "status": "not_started",
            "current_trial": 0,
            "total_trials": 0,
            "best_value": None,
            "study_name": None,
        }

    # 扫描所有 .db 文件
    db_files = list(hpo_dir.glob("*.db"))

    if not db_files:
        return {
            "status": "not_started",
            "current_trial": 0,
            "total_trials": 0,
            "best_value": None,
            "study_name": None,
        }

    # 获取最新的 study
    latest_db = max(db_files, key=lambda f: f.stat().st_mtime)
    study_name = latest_db.stem

    current_trial = 0
    total_trials = 0
    run_status = "completed"
    best_value = None

    try:
        conn = sqlite3.connect(str(latest_db))
        cursor = conn.cursor()

        # 获取已完成试验数
        cursor.execute("SELECT COUNT(*) FROM trials WHERE state = 'COMPLETE'")
        current_trial = cursor.fetchone()[0]

        # 获取总试验数
        cursor.execute("SELECT COUNT(*) FROM trials")
        total_trials = cursor.fetchone()[0]

        # 检查是否有 RUNNING 状态
        cursor.execute("SELECT COUNT(*) FROM trials WHERE state = 'RUNNING'")
        running_count = cursor.fetchone()[0]
        if running_count > 0:
            run_status = "running"

        # 获取最佳值
        cursor.execute("""
            SELECT value FROM trials
            WHERE state = 'COMPLETE' AND value IS NOT NULL
            ORDER BY value DESC
            LIMIT 1
        """)
        row = cursor.fetchone()
        if row:
            best_value = row[0]

        conn.close()
    except Exception:
        pass

    return {
        "status": run_status,
        "current_trial": current_trial,
        "total_trials": total_trials,
        "best_value": best_value,
        "study_name": study_name,
    }


def _get_backtest_summary() -> dict:
    """获取回测摘要"""
    import json

    results_dir = Path("data/results/results")
    metrics_path = results_dir / "metrics_summary.json"

    if not metrics_path.exists():
        return {
            "has_results": False,
            "sharpe_ratio": None,
            "ann_return": None,
            "max_drawdown": None,
        }

    try:
        with open(metrics_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        return {
            "has_results": True,
            "sharpe_ratio": data.get("sharpe_ratio"),
            "ann_return": data.get("ann_return"),
            "max_drawdown": data.get("max_drawdown"),
        }
    except Exception:
        return {
            "has_results": False,
            "sharpe_ratio": None,
            "ann_return": None,
            "max_drawdown": None,
        }


def _get_data_layers_summary() -> dict:
    """获取数据层摘要"""
    from src.data_layer.layer_manager import DataLayerManager

    try:
        cfg = load_config()
        mgr = DataLayerManager(cfg)
        status = mgr.check_all_layers()

        total = len(status)
        needs_update = sum(1 for s in status.values() if s.needs_update)

        return {
            "total": total,
            "needs_update": needs_update,
        }
    except Exception:
        return {
            "total": 2,  # canonical, raw_feature
            "needs_update": 0,
        }


def _get_models_summary() -> dict:
    """获取模型摘要"""
    try:
        from src.formalization.model_registry import ModelRegistry, ModelStatus

        registry = ModelRegistry.from_config()
        models = registry.list(limit=1000)

        total = len(models)
        by_status = {}

        for status_val in ModelStatus:
            status_models = registry.list(status=status_val.value, limit=1000)
            by_status[status_val.value] = len(status_models)

        return {
            "total": total,
            "by_status": by_status,
        }
    except Exception:
        return {
            "total": 0,
            "by_status": {},
        }


def _get_tasks_summary() -> dict:
    """获取任务摘要"""
    try:
        from src.tasking.store import TaskStore
        from src.tasking.models import TaskStatus

        store = TaskStore()
        tasks = store.list_tasks(limit=1000)

        total = len(tasks)
        by_status = {}

        for status in TaskStatus:
            by_status[status.value] = 0

        for task in tasks:
            status_val = task.status.value
            by_status[status_val] = by_status.get(status_val, 0) + 1

        return {
            "total": total,
            "by_status": by_status,
        }
    except Exception:
        return {
            "total": 0,
            "by_status": {},
        }


def _get_stocks_summary() -> dict:
    """获取股票摘要"""
    try:
        from src.data_layer.db import get_connection

        cfg = load_config()
        con = get_connection(cfg)

        # 检查是否有 stock_latest 缓存表
        try:
            total = con.execute("SELECT COUNT(*) FROM stock_latest").fetchone()[0]
        except Exception:
            total = con.execute("SELECT COUNT(DISTINCT code) FROM daily_bar").fetchone()[0]

        # 总数据条数
        try:
            total_bars = con.execute("SELECT SUM(bar_count) FROM stock_latest").fetchone()[0] or 0
        except Exception:
            total_bars = con.execute("SELECT COUNT(*) FROM daily_bar").fetchone()[0] or 0

        return {
            "total": total,
            "total_bars": total_bars,
        }
    except Exception:
        return {
            "total": 0,
            "total_bars": 0,
        }


# ================================================================
# 端点实现
# ================================================================
@router.get("/summary", response_model=DashboardSummaryResponse)
async def get_dashboard_summary():
    """
    获取 Dashboard 聚合统计数据

    汇总各模块的关键指标，供前端 Dashboard 使用。
    """
    # 并行获取各模块数据
    iterations_data = _get_iterations_count()
    hpo_data = _get_hpo_summary()
    backtest_data = _get_backtest_summary()
    data_layers_data = _get_data_layers_summary()
    models_data = _get_models_summary()
    tasks_data = _get_tasks_summary()
    stocks_data = _get_stocks_summary()

    return DashboardSummaryResponse(
        iterations=IterationsSummary(total=iterations_data),
        hpo=HPOSummary(**hpo_data),
        backtest=BacktestSummary(**backtest_data),
        data_layers=DataLayersSummary(**data_layers_data),
        models=ModelsSummary(**models_data),
        tasks=TasksSummary(**tasks_data),
        stocks=StocksSummary(**stocks_data),
    )
