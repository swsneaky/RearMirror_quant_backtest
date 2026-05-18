"""
API 路由模块
"""
from api.routes.data_layers import router as data_layers_router
from api.routes.backtest import router as backtest_router
from api.routes.hpo import router as hpo_router
from api.routes.iterations import router as iterations_router
from api.routes.stacking import router as stacking_router
from api.routes.formalization import router as formalization_router
from api.routes.config import router as config_router
from api.routes.tasks import router as tasks_router
from api.routes.stocks import router as stocks_router
from api.routes.dashboard import router as dashboard_router
from api.routes.factors import router as factors_router

__all__ = [
    "data_layers_router",
    "backtest_router",
    "hpo_router",
    "iterations_router",
    "stacking_router",
    "formalization_router",
    "config_router",
    "tasks_router",
    "stocks_router",
    "dashboard_router",
    "factors_router",
]
