"""
数据层状态 API

端点:
  GET /api/data-layers           -- 获取所有数据层状态
  GET /api/data-layers/{layer}   -- 获取指定层详细状态
  POST /api/data-layers/refresh  -- 刷新指纹缓存
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.config_loader import load_config
from src.data_layer.layer_manager import (
    DataLayerManager,
    LayerStatus,
    load_layer_fingerprint,
    compute_cache_fingerprint,
    compute_canonical_fingerprint,
    compute_config_fingerprint,
)

router = APIRouter(prefix="/api/data-layers", tags=["data-layers"])


# ================================================================
# 响应模型
# ================================================================
from pydantic import BaseModel
from typing import Optional


class LayerStatusResponse(BaseModel):
    """单层状态响应"""
    layer_name: str
    output_exists: bool
    fingerprint_exists: bool
    upstream_changed: bool
    config_changed: bool
    needs_update: bool
    reason: str


class LayerDetailResponse(BaseModel):
    """单层详细状态响应"""
    layer_name: str
    output_path: str
    output_exists: bool
    fingerprint_exists: bool
    upstream_fingerprint: Optional[str] = None
    config_fingerprint: Optional[str] = None
    upstream_changed: bool
    config_changed: bool
    needs_update: bool
    reason: str
    row_count: Optional[int] = None
    n_stocks: Optional[int] = None
    n_features: Optional[int] = None
    created_at: Optional[str] = None


class AllLayersResponse(BaseModel):
    """所有层状态响应"""
    layers: dict[str, LayerStatusResponse]
    summary: dict


# ================================================================
# 端点实现
# ================================================================
def _get_manager() -> DataLayerManager:
    """获取 DataLayerManager 实例"""
    cfg = load_config()
    return DataLayerManager(cfg)


@router.get("", response_model=AllLayersResponse)
async def get_all_layers():
    """
    获取所有数据层状态

    返回各层的：
    - 产物是否存在
    - 指纹是否存在
    - 上游是否变化
    - 配置是否变化
    - 是否需要更新
    """
    mgr = _get_manager()
    status = mgr.check_all_layers()

    layers = {}
    needs_update_count = 0

    for layer_name, s in status.items():
        layers[layer_name] = LayerStatusResponse(
            layer_name=s.layer_name,
            output_exists=s.output_exists,
            fingerprint_exists=s.fingerprint_exists,
            upstream_changed=s.upstream_changed,
            config_changed=s.config_changed,
            needs_update=s.needs_update,
            reason=s.reason,
        )
        if s.needs_update:
            needs_update_count += 1

    return AllLayersResponse(
        layers=layers,
        summary={
            "total_layers": len(layers),
            "needs_update": needs_update_count,
            "all_up_to_date": needs_update_count == 0,
        },
    )


@router.get("/{layer_name}", response_model=LayerDetailResponse)
async def get_layer_detail(layer_name: str):
    """
    获取指定数据层的详细状态

    支持的层名：
    - canonical (Layer 1)
    - raw_feature (Layer 2)
    """
    valid_layers = ["canonical", "raw_feature"]
    if layer_name not in valid_layers:
        raise HTTPException(
            status_code=400,
            detail=f"无效的层名: {layer_name}。支持: {valid_layers}",
        )

    mgr = _get_manager()
    status = mgr.check_layer(layer_name)

    # 加载详细指纹
    fp = load_layer_fingerprint(layer_name)

    return LayerDetailResponse(
        layer_name=status.layer_name,
        output_path=mgr.get_canonical_path() if layer_name == "canonical" else mgr.get_raw_feature_path(),
        output_exists=status.output_exists,
        fingerprint_exists=status.fingerprint_exists,
        upstream_fingerprint=fp.upstream_fingerprint if fp else None,
        config_fingerprint=fp.config_fingerprint if fp else None,
        upstream_changed=status.upstream_changed,
        config_changed=status.config_changed,
        needs_update=status.needs_update,
        reason=status.reason,
        row_count=fp.row_count if fp else None,
        n_stocks=fp.n_stocks if fp else None,
        n_features=fp.n_features if fp else None,
        created_at=fp.created_at if fp else None,
    )


@router.post("/refresh")
async def refresh_fingerprints():
    """
    刷新指纹缓存

    重新计算所有层的当前指纹，但不更新保存的指纹文件。
    用于检查当前状态是否有变化。
    """
    mgr = _get_manager()

    return {
        "current_fingerprints": {
            "cache": {
                "fingerprint": mgr.get_cache_fingerprint(),
                "path": mgr.get_cache_dir(),
            },
            "canonical": {
                "upstream_fingerprint": mgr.get_canonical_fingerprint(),
                "config_fingerprint": mgr.get_etl_config_fingerprint(),
                "path": mgr.get_canonical_path(),
            },
            "raw_feature": {
                "upstream_fingerprint": mgr.get_raw_feature_upstream_fingerprint(),
                "config_fingerprint": mgr.get_feature_config_fingerprint(),
                "path": mgr.get_raw_feature_path(),
            },
        },
    }


@router.get("/cache/stats")
async def get_cache_stats():
    """
    获取 Layer 0 (缓存) 统计信息

    返回缓存目录的文件数、总大小等统计。
    """
    import os
    from src.config_loader import load_config

    cfg = load_config()
    cache_dir = cfg["etl"].get("cache_dir", "data/stock_daily_cache")

    if not os.path.isdir(cache_dir):
        return {
            "path": cache_dir,
            "exists": False,
            "file_count": 0,
            "total_size": 0,
        }

    files = [
        f for f in os.listdir(cache_dir)
        if f.endswith(".parquet") and not f.startswith("_")
    ]

    total_size = 0
    for f in files:
        fp = os.path.join(cache_dir, f)
        try:
            total_size += os.path.getsize(fp)
        except OSError:
            pass

    return {
        "path": cache_dir,
        "exists": True,
        "file_count": len(files),
        "total_size": total_size,
        "total_size_human": _human_size(total_size),
        "fingerprint": compute_cache_fingerprint(cache_dir),
    }


def _human_size(nbytes: int) -> str:
    """字节转人类可读格式"""
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"
