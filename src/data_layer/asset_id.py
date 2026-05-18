"""
Asset ID 生成器 -- 确定性版本标识

协议:
  asset_id = "{asset_type}__{sha256(config_payload)[:12]}"

  - config_payload 经 json.dumps(sort_keys=True) 序列化
  - 同配置 -> 同 ID (幂等)
  - 不同配置 -> 不同 ID (多版本共存)
"""
from __future__ import annotations

import hashlib
import json


def make_config_hash(config_dict: dict) -> str:
    """将配置字典序列化为 SHA256 哈希 (完整 64 位)"""
    payload = json.dumps(config_dict, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def make_asset_id(asset_type: str, config_dict: dict) -> str:
    """
    生成确定性 asset_id.

    Examples:
        make_asset_id("feature_set", {"active_factors": ["kline","rolling"], "windows": [5,10]})
        -> "feature_set__a1b2c3d4e5f6"
    """
    h = make_config_hash(config_dict)
    return f"{asset_type}__{h[:12]}"


def make_factor_id(factor_group: str, code_hash: str) -> str:
    """因子定义 ID: '{group}__{code_hash[:12]}'"""
    return f"{factor_group}__{code_hash[:12]}"


def make_table_name(asset_type: str, config_dict: dict) -> str:
    """
    物化表名: 'feat__{hash[:12]}' 或 'label__{hash[:12]}'

    缩写映射:
      feature_set -> feat
      label_set   -> label
    """
    prefix_map = {
        "feature_set": "feat",
        "label_set": "label",
    }
    prefix = prefix_map.get(asset_type, asset_type)
    h = make_config_hash(config_dict)
    return f"{prefix}__{h[:12]}"
