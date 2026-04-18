"""
模型工厂 -- 从注册表动态查找, 不再硬编码 if/elif
铁律六：所有模型封装成 .fit(X, y) / .predict(X) 标准接口
         外层并行时内层 n_jobs=1 (已在 config 中锁定)

扩展方式: 在 src/models/ 下新建 .py, 用 @registry.register_model 装饰
"""
from __future__ import annotations

import src.models  # noqa: F401  触发内置模型注册
from src.registry import registry


def build_model(cfg: dict):
    """根据 config 中 model.active 从注册表实例化模型"""
    active = cfg["model"]["active"]
    params = dict(cfg["model"].get(active, {}))
    model_cls = registry.get_model(active)
    return model_cls(**params)
