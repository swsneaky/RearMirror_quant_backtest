"""内置模型：LightGBM, XGBoost, RandomForest -- 直接注册 sklearn 兼容类"""
import lightgbm as lgb
import xgboost as xgb
from sklearn.ensemble import RandomForestRegressor

from src.registry import registry

registry.register_model("lightgbm")(lgb.LGBMRegressor)
registry.register_model("xgboost")(xgb.XGBRegressor)
registry.register_model("random_forest")(RandomForestRegressor)
