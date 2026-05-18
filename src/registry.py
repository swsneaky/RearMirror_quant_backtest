"""
全局注册表 -- 因子和模型的插件发现机制

v2 升级: 因子注册支持 FactorMeta 声明 (输入列、输出列、描述)

用法:
    @registry.register_factor("my_group", meta=FactorMeta(
        group="my_group",
        input_cols=["raw_open", "raw_close"],
        output_cols=["feat_xxx"],
    ))
    def my_factor(df, grouped, windows, f32):
        ...
        return df, ["feat_xxx", ...]

    @registry.register_model("catboost")
    class CatBoostWrapper:
        def __init__(self, **params): ...
        def fit(self, X, y): ...
        def predict(self, X): ...
"""
from __future__ import annotations

import hashlib
import inspect
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class FactorMeta:
    """因子元数据声明 -- 每个因子函数必须提供"""
    group: str                          # 因子组名: 'kline', 'rolling', ...
    input_cols: list[str]               # 所需原始列: ["raw_open", "raw_close", ...]
    output_cols: list[str]              # 产出列 (静态已知的): ["feat_KMID", ...]
    description: str = ""               # 人类可读描述
    windowed: bool = False              # 是否随 windows 参数扩展输出列


class _Registry:
    """单例注册表，存放所有可插拔的因子函数和模型类"""

    def __init__(self):
        self._factors: dict[str, Callable] = {}
        self._factor_meta: dict[str, FactorMeta] = {}
        self._factor_code_hash: dict[str, str] = {}
        self._models: dict[str, type | Callable] = {}

    # --------------------------------------------------
    # 因子注册
    # --------------------------------------------------
    def register_factor(self, name: str, meta: FactorMeta | None = None):
        """
        装饰器：注册一个因子生成函数。

        Parameters
        ----------
        name : 因子组名
        meta : 因子元数据 (v2, 可选但建议提供)

        被装饰函数签名:
            (df: DataFrame, grouped: GroupBy, windows: list[int], f32: str)
            -> (df: DataFrame, feature_names: list[str])
        """
        def decorator(fn: Callable):
            if name in self._factors:
                raise KeyError(f"因子 '{name}' 已注册，不允许重复")
            self._factors[name] = fn

            # v2: 存储元数据和代码哈希
            if meta is not None:
                self._factor_meta[name] = meta
            try:
                source = inspect.getsource(fn)
                code_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
            except (OSError, TypeError):
                code_hash = ""
            self._factor_code_hash[name] = code_hash

            return fn
        return decorator

    def get_factor(self, name: str) -> Callable:
        if name not in self._factors:
            raise KeyError(
                f"因子 '{name}' 未注册。可用: {list(self._factors.keys())}"
            )
        return self._factors[name]

    def get_factor_meta(self, name: str) -> FactorMeta | None:
        """获取因子元数据, 未声明返回 None"""
        return self._factor_meta.get(name)

    def get_factor_code_hash(self, name: str) -> str:
        """获取因子函数的代码哈希"""
        return self._factor_code_hash.get(name, "")

    def list_factors(self) -> list[str]:
        return list(self._factors.keys())

    # --------------------------------------------------
    # 模型注册
    # --------------------------------------------------
    def register_model(self, name: str):
        """
        装饰器：注册一个模型类或工厂函数。
        被注册对象必须支持: cls(**params).fit(X, y) / .predict(X)
        """
        def decorator(cls):
            if name in self._models:
                raise KeyError(f"模型 '{name}' 已注册，不允许重复")
            self._models[name] = cls
            return cls
        return decorator

    def get_model(self, name: str):
        if name not in self._models:
            raise KeyError(
                f"模型 '{name}' 未注册。可用: {list(self._models.keys())}"
            )
        return self._models[name]

    def list_models(self) -> list[str]:
        return list(self._models.keys())


# 全局唯一实例
registry = _Registry()
