from __future__ import annotations

import copy
from typing import Any


DEFAULT_RUNTIME_CONFIG: dict[str, Any] = {
    "default_mode": "formal",
    "shared_machine_default_mode": "shared_machine",
    "modes": {
        "formal": {
            "description": (
                "正式全量 materialization；保留完整特征列、全日期范围与原始回测窗口。"
            ),
            "recent_trade_dates": None,
            "feature_limit": None,
            "neutralize_chunk_days": 256,
            "backtest_overrides": {},
        },
        "shared_machine": {
            "description": (
                "共享机器降级取证模式；裁剪到最近 260 个交易日和前 32 个特征，"
                "并缩小回测窗口。"
            ),
            "recent_trade_dates": 260,
            "feature_limit": 32,
            "neutralize_chunk_days": 128,
            "backtest_overrides": {
                "train_window": 120,
                "test_step": 20,
            },
        },
    },
}


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def get_runtime_config(cfg: dict | None) -> dict[str, Any]:
    runtime_cfg = copy.deepcopy(DEFAULT_RUNTIME_CONFIG)
    if cfg and isinstance(cfg.get("runtime"), dict):
        runtime_cfg = _deep_merge(runtime_cfg, cfg["runtime"])
    return runtime_cfg


def resolve_runtime_mode(
    cfg: dict | None,
    requested_mode: str | None = None,
) -> tuple[str, dict[str, Any]]:
    runtime_cfg = get_runtime_config(cfg)
    mode = requested_mode or runtime_cfg.get("default_mode") or "formal"
    modes = runtime_cfg.get("modes", {})
    if mode not in modes:
        raise ValueError(
            f"未知 runtime_mode={mode!r}，可选值: {', '.join(sorted(modes))}"
        )

    resolved = copy.deepcopy(modes[mode])
    resolved.setdefault("description", "")
    resolved.setdefault("recent_trade_dates", None)
    resolved.setdefault("feature_limit", None)
    resolved.setdefault("neutralize_chunk_days", None)
    resolved.setdefault("backtest_overrides", {})
    return mode, resolved


def plan_to_config_payload(plan: dict[str, Any] | None) -> dict[str, Any] | None:
    if not plan:
        return None
    payload = copy.deepcopy(plan)
    if payload.get("date_range") is not None:
        payload["date_range"] = list(payload["date_range"])
    return payload


def apply_runtime_mode_to_config(
    cfg: dict,
    mode: str,
    plan: dict[str, Any] | None = None,
) -> dict:
    run_cfg = copy.deepcopy(cfg)
    runtime_cfg = run_cfg.setdefault("runtime", {})
    runtime_cfg["active_mode"] = mode
    if plan:
        runtime_cfg["resolved_plan"] = plan_to_config_payload(plan)

    overrides = copy.deepcopy((plan or {}).get("backtest_overrides") or {})
    if overrides:
        run_cfg.setdefault("backtest", {}).update(overrides)
    return run_cfg
