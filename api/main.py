"""
RearMirror FastAPI 主入口

用法:
    uvicorn api.main:app --reload --port 8000
    或
    python run_api.py
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import data_layers_router, backtest_router, hpo_router, iterations_router, stacking_router, formalization_router, config_router, tasks_router, stocks_router, dashboard_router, factors_router


# ================================================================
# 生命周期管理 - 启动 TaskExecutor
# ================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化 TaskExecutor"""
    from src.tasking.executor import TaskExecutor

    executor = TaskExecutor(max_workers=2, poll_interval=2.0)
    executor.start()
    print("[API] TaskExecutor 已启动，开始处理任务队列")

    yield  # 应用运行

    # 关闭时停止 executor
    executor.stop()
    print("[API] TaskExecutor 已停止")


# 创建 FastAPI 应用
app = FastAPI(
    title="RearMirror API",
    description="数据层状态与迭代结果 API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS 配置 (允许前端跨域访问)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制为具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ================================================================
# 健康检查
# ================================================================
@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {"status": "ok", "service": "RearMirror API"}


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": "RearMirror API",
        "version": "0.1.0",
        "endpoints": [
            "/health",
            "/api/data-layers",
            "/api/data-layers/{layer}",
            "/api/data-layers/refresh",
            "/api/data-layers/cache/stats",
            "/api/backtest/results",
            "/api/backtest/iterations",
            "/api/backtest/run",
            "/api/backtest/nav",
            "/api/hpo/status",
            "/api/hpo/trials",
            "/api/hpo/{study_name}/report",
            "/api/iterations",
            "/api/iterations/{id}",
            "/api/iterations/{id}/brief",
            "/api/iterations/{id}/artifacts",
            "/api/stacking/status",
            "/api/stacking/train",
            "/api/stacking/models",
            "/api/models/register",
            "/api/models/register/experiment",
            "/api/models/promote",
            "/api/models/registry",
            "/api/models/{model_id}",
            "/api/models/promoted/latest",
            "/api/models/promotion/criteria",
            "/api/config",
            "/api/config/etl",
            "/api/config/features",
            "/api/config/cross_section",
            "/api/config/options",
            "/api/tasks",
            "/api/tasks/{task_id}",
            "/api/tasks/{task_id}/cancel",
            "/api/tasks/{task_id}/retry",
            "/api/dashboard/summary",
            "/api/factors/summary",
            "/api/factors/ic-series",
            "/api/factors/correlation",
            "/api/factors/run",
        ],
    }


# ================================================================
# 注册路由
# ================================================================
app.include_router(data_layers_router)
app.include_router(backtest_router)
app.include_router(hpo_router)
app.include_router(iterations_router)
app.include_router(stacking_router)
app.include_router(formalization_router)
app.include_router(config_router)
app.include_router(tasks_router)
app.include_router(stocks_router)
app.include_router(dashboard_router)
app.include_router(factors_router)
