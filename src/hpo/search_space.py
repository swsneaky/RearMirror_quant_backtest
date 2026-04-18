"""
超参数搜索空间定义

支持模型:
  - lightgbm
  - xgboost
  - random_forest

搜索空间设计原则:
  1. 支持从配置文件 (hpo.search_space) 读取参数范围
  2. 配置未提供时使用内置默认范围
  3. 使用 Optuna 的 suggest_* 方法定义
  4. 支持 float/int/categorical 三种类型
"""
from typing import Any, Callable

# 默认搜索空间范围 (当配置未提供时使用)
DEFAULT_SEARCH_SPACE = {
    "lightgbm": {
        "n_estimators": (100, 500, 50),      # (min, max, step)
        "learning_rate": (0.01, 0.15, True), # (min, max, log=True)
        "max_depth": (3, 8, None),           # (min, max, step=None)
    },
    "xgboost": {
        "n_estimators": (100, 500, 50),
        "learning_rate": (0.01, 0.15, True),
        "max_depth": (3, 8, None),
    },
    "random_forest": {
        "n_estimators": (50, 300, 50),
        "max_depth": (5, 20, None),
    },
}


def get_search_space(model_name: str, cfg: dict | None = None) -> Callable:
    """
    返回对应模型的搜索空间定义函数

    Args:
        model_name: 模型名称 (lightgbm, xgboost, random_forest)
        cfg: 配置字典，可包含 hpo.search_space 段

    Returns:
        搜索空间定义函数，接受 trial 对象，返回参数字典
    """
    spaces = {
        "lightgbm": _lightgbm_search_space,
        "xgboost": _xgboost_search_space,
        "random_forest": _random_forest_search_space,
    }
    if model_name not in spaces:
        raise ValueError(f"不支持的模型: {model_name}，支持: {list(spaces.keys())}")

    # 返回带配置的闭包
    def search_space_wrapper(trial) -> dict[str, Any]:
        return spaces[model_name](trial, cfg=cfg)

    return search_space_wrapper


def _lightgbm_search_space(trial, cfg: dict | None = None) -> dict[str, Any]:
    """
    LightGBM 超参数搜索空间

    支持从配置读取参数范围 (cfg.hpo.search_space.lightgbm)。
    配置格式: {param_name: [min, max]} 或使用默认范围。

    参考 base_config.yaml 默认值:
      - n_estimators: 200
      - learning_rate: 0.05
      - max_depth: 4
      - num_leaves: 12
      - min_child_samples: 800
      - reg_lambda: 10.0
      - reg_alpha: 1.0
      - colsample_bytree: 0.8
      - subsample: 0.8
    """
    # 从配置读取参数范围
    config_space = _get_config_search_space("lightgbm", cfg)

    return {
        # 迭代相关 (支持配置覆盖)
        "n_estimators": trial.suggest_int(
            "n_estimators",
            config_space.get("n_estimators", (100, 500))[0],
            config_space.get("n_estimators", (100, 500))[1],
            step=50,
        ),
        "learning_rate": trial.suggest_float(
            "learning_rate",
            config_space.get("learning_rate", (0.01, 0.15))[0],
            config_space.get("learning_rate", (0.01, 0.15))[1],
            log=True,
        ),

        # 树结构
        "max_depth": trial.suggest_int(
            "max_depth",
            config_space.get("max_depth", (3, 8))[0],
            config_space.get("max_depth", (3, 8))[1],
        ),
        "num_leaves": trial.suggest_int("num_leaves", 8, 64),
        "min_child_samples": trial.suggest_int("min_child_samples", 200, 2000, step=100),

        # 正则化
        "reg_lambda": trial.suggest_float("reg_lambda", 0.1, 50.0, log=True),
        "reg_alpha": trial.suggest_float("reg_alpha", 0.0, 10.0),

        # 采样
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
        "subsample": trial.suggest_float("subsample", 0.5, 1.0),

        # 固定参数 (不参与搜索)
        "objective": "huber",
        "boosting_type": "gbdt",
        "verbose": -1,
        "random_state": 42,
        "n_jobs": 1,
        "importance_type": "gain",
    }


def _xgboost_search_space(trial, cfg: dict | None = None) -> dict[str, Any]:
    """
    XGBoost 超参数搜索空间

    支持从配置读取参数范围 (cfg.hpo.search_space.xgboost)。
    配置格式: {param_name: [min, max]} 或使用默认范围。

    参考 base_config.yaml 默认值:
      - n_estimators: 200
      - learning_rate: 0.05
      - max_depth: 4
      - max_leaves: 12
      - min_child_weight: 1.0
      - gamma: 0.1
      - reg_lambda: 10.0
      - reg_alpha: 1.0
      - colsample_bytree: 0.8
      - subsample: 0.8
    """
    # 从配置读取参数范围
    config_space = _get_config_search_space("xgboost", cfg)

    return {
        # 迭代相关 (支持配置覆盖)
        "n_estimators": trial.suggest_int(
            "n_estimators",
            config_space.get("n_estimators", (100, 500))[0],
            config_space.get("n_estimators", (100, 500))[1],
            step=50,
        ),
        "learning_rate": trial.suggest_float(
            "learning_rate",
            config_space.get("learning_rate", (0.01, 0.15))[0],
            config_space.get("learning_rate", (0.01, 0.15))[1],
            log=True,
        ),

        # 树结构
        "max_depth": trial.suggest_int(
            "max_depth",
            config_space.get("max_depth", (3, 8))[0],
            config_space.get("max_depth", (3, 8))[1],
        ),
        "max_leaves": trial.suggest_int("max_leaves", 8, 64),
        "min_child_weight": trial.suggest_float("min_child_weight", 0.1, 10.0),
        "gamma": trial.suggest_float("gamma", 0.0, 1.0),

        # 正则化
        "reg_lambda": trial.suggest_float("reg_lambda", 0.1, 50.0, log=True),
        "reg_alpha": trial.suggest_float("reg_alpha", 0.0, 10.0),

        # 采样
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
        "subsample": trial.suggest_float("subsample", 0.5, 1.0),

        # 固定参数
        "objective": "reg:squarederror",
        "grow_policy": "lossguide",
        "tree_method": "hist",
        "random_state": 42,
        "n_jobs": 1,
        "verbosity": 0,
    }


def _random_forest_search_space(trial, cfg: dict | None = None) -> dict[str, Any]:
    """
    RandomForest 超参数搜索空间

    支持从配置读取参数范围 (cfg.hpo.search_space.random_forest)。
    配置格式: {param_name: [min, max]} 或使用默认范围。

    参考 base_config.yaml 默认值:
      - n_estimators: 100
      - max_depth: 10
      - min_samples_leaf: 200
      - min_samples_split: 400
      - max_features: 0.8
      - max_samples: 0.8
      - ccp_alpha: 0.01
    """
    # 从配置读取参数范围
    config_space = _get_config_search_space("random_forest", cfg)

    return {
        # 树数量 (支持配置覆盖)
        "n_estimators": trial.suggest_int(
            "n_estimators",
            config_space.get("n_estimators", (50, 300))[0],
            config_space.get("n_estimators", (50, 300))[1],
            step=50,
        ),

        # 树结构
        "max_depth": trial.suggest_int(
            "max_depth",
            config_space.get("max_depth", (5, 20))[0],
            config_space.get("max_depth", (5, 20))[1],
        ),
        "min_samples_leaf": trial.suggest_int("min_samples_leaf", 50, 500, step=50),
        "min_samples_split": trial.suggest_int("min_samples_split", 100, 1000, step=100),

        # 采样
        "max_features": trial.suggest_float("max_features", 0.3, 1.0),
        "max_samples": trial.suggest_float("max_samples", 0.5, 1.0),

        # 正则化
        "ccp_alpha": trial.suggest_float("ccp_alpha", 1e-6, 0.1, log=True),

        # 固定参数
        "criterion": "squared_error",
        "bootstrap": True,
        "random_state": 42,
        "n_jobs": 1,
    }


def _get_config_search_space(model_name: str, cfg: dict | None = None) -> dict[str, tuple]:
    """
    从配置中提取指定模型的搜索空间范围

    Args:
        model_name: 模型名称
        cfg: 配置字典

    Returns:
        参数范围字典 {param_name: (min, max)}
    """
    if cfg is None:
        return {}

    hpo_cfg = cfg.get("hpo", {})
    search_space_cfg = hpo_cfg.get("search_space", {})
    model_space = search_space_cfg.get(model_name, {})

    # 将 [min, max] 列表转换为 (min, max) 元组
    result = {}
    for param_name, value in model_space.items():
        if isinstance(value, (list, tuple)) and len(value) == 2:
            result[param_name] = (value[0], value[1])

    return result


def get_backtest_search_space(trial) -> dict[str, Any]:
    """
    回测参数搜索空间 (可选，用于联合优化)

    包含:
      - train_window: 训练窗口
      - top_k: 持仓数量
    """
    return {
        "train_window": trial.suggest_int("train_window", 200, 800, step=100),
        "top_k": trial.suggest_int("top_k", 20, 50, step=5),
    }


def merge_params(base_cfg: dict, model_name: str, trial) -> dict:
    """
    合并基础配置和搜索空间参数

    Args:
        base_cfg: 基础配置字典
        model_name: 模型名称
        trial: Optuna trial 对象

    Returns:
        合并后的配置字典
    """
    cfg = base_cfg.copy()

    # 获取模型搜索空间 (传入配置以支持配置驱动的参数范围)
    model_params = get_search_space(model_name, cfg=cfg)(trial)

    # 更新模型配置
    cfg["model"] = cfg.get("model", {}).copy()
    cfg["model"]["active"] = model_name
    cfg["model"][model_name] = cfg["model"].get(model_name, {}).copy()
    cfg["model"][model_name].update(model_params)

    return cfg
