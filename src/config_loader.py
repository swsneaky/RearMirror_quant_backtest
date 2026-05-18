"""
全局配置加载器 -- 唯一真理来源
铁律一：所有模块通过此接口读取参数，禁止硬编码

多实验支持:
  load_config("configs/base_config.yaml")          -> 返回基础配置
  load_config("experiments/exp_001/config.yaml")   -> 返回完整快照
  load_experiment_config("configs/profiles/xx.yaml") -> base + overlay 自动合并
"""
import copy
import os
import yaml
from pathlib import Path


def _find_config_path() -> Path:
    """从环境变量 / 项目根目录查找 configs/base_config.yaml"""
    search = Path(os.environ.get("QUANT_CONFIG", ""))
    if search.is_file():
        return search
    for anchor in (Path(__file__).resolve().parent.parent, Path.cwd()):
        candidate = anchor / "configs" / "base_config.yaml"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("找不到 configs/base_config.yaml，请设置 QUANT_CONFIG 环境变量")


def _find_base_config() -> Path:
    """总是返回 base_config.yaml 路径（不受 QUANT_CONFIG 影响）"""
    for anchor in (Path(__file__).resolve().parent.parent, Path.cwd()):
        candidate = anchor / "configs" / "base_config.yaml"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("找不到 configs/base_config.yaml")


def _deep_merge(base: dict, overlay: dict) -> dict:
    """递归深合并：overlay 覆盖 base，dict 递归合并，其余直接覆盖"""
    merged = copy.deepcopy(base)
    for key, val in overlay.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(val, dict):
            merged[key] = _deep_merge(merged[key], val)
        else:
            merged[key] = copy.deepcopy(val)
    return merged


def _ensure_paths(cfg: dict) -> None:
    """自动创建路径目录"""
    for key in ("data_raw", "data_features", "data_results", "data_cache", "models", "logs"):
        p = cfg.get("paths", {}).get(key)
        if p:
            os.makedirs(p, exist_ok=True)


def load_config(path: str | Path | None = None) -> dict:
    """加载单个 YAML 配置文件并返回字典"""
    cfg_path = Path(path) if path else _find_config_path()
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # 统一路径解析器填充缺省值 (setdefault, 不覆盖 YAML 已有配置)
    from src.paths import project_paths
    project_paths.inject_into_config(cfg)
    _ensure_paths(cfg)
    return cfg


def load_experiment_config(
    profile_path: str | Path,
    exp_dir: str | Path | None = None,
) -> dict:
    """
    加载实验配置 = base_config + profile overlay。

    Parameters
    ----------
    profile_path : 实验 profile YAML 路径（只需写覆盖项）
    exp_dir : 实验输出目录，若提供则自动将 features.output /
              paths.models / paths.logs / analysis.* 重定向到此目录

    Returns
    -------
    合并后的完整配置字典
    """
    base = load_config(_find_base_config())
    with open(profile_path, "r", encoding="utf-8") as f:
        overlay = yaml.safe_load(f) or {}
    cfg = _deep_merge(base, overlay)

    # 自动注入实验路径
    if exp_dir is not None:
        exp_dir = str(exp_dir)
        cfg["features"]["output"] = os.path.join(exp_dir, "features", "alpha158.parquet")
        cfg["paths"]["models"] = os.path.join(exp_dir, "models")
        cfg["paths"]["logs"] = os.path.join(exp_dir, "logs")
        cfg["paths"]["data_features"] = os.path.join(exp_dir, "features")
        ana = cfg.get("analysis", {})
        ana["ic_output"] = os.path.join(exp_dir, "features", "ic_series.parquet")
        ana["icir_output"] = os.path.join(exp_dir, "features", "icir.parquet")
        ana["ic_decay_output"] = os.path.join(exp_dir, "features", "ic_decay.parquet")
        ana["shap_output"] = os.path.join(exp_dir, "features", "shap_importance.parquet")
        cfg["analysis"] = ana

    _ensure_paths(cfg)
    return cfg
