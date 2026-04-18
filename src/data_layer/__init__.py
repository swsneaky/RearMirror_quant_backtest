"""
数据资产层 -- 分层管理 canonical -> feature -> label -> dataset

SQLite 统一数据库支持 (WAL 模式, 支持多进程并发):
  db.get_connection(cfg)  -- 获取全局连接
  db.cursor(cfg)          -- 上下文管理器
  db.table_exists(cfg, t) -- 检查表存在
  db.list_table_columns() -- 列出表列名

v2 版本化资产:
  asset_id.make_asset_id()  -- 确定性资产 ID
  db.register_asset()       -- 注册资产到目录
  db.register_factor_def()  -- 注册因子定义

v3 数据层依赖管理:
  layer_manager.DataLayerManager -- 分层依赖追踪与增量更新
  layer_manager.check_data_layers() -- 检查所有数据层状态
"""
from src.data_layer.canonical import CanonicalStore
from src.data_layer.feature_store import FeatureStore
from src.data_layer.label_store import LabelStore
from src.data_layer.dataset_builder import DatasetBuilder
from src.data_layer.db import (
    get_connection, get_db_path, cursor, table_exists, table_row_count,
    list_table_columns,
    register_asset, get_asset, list_assets,
    register_factor_def, register_feature_set_factors,
)
from src.data_layer.asset_id import make_asset_id, make_config_hash, make_table_name
from src.data_layer.layer_manager import (
    DataLayerManager, LayerFingerprint, LayerStatus,
    check_data_layers, print_data_layer_report,
)

__all__ = [
    "CanonicalStore", "FeatureStore", "LabelStore", "DatasetBuilder",
    "get_connection", "get_db_path", "cursor", "table_exists", "table_row_count",
    "list_table_columns",
    "register_asset", "get_asset", "list_assets",
    "register_factor_def", "register_feature_set_factors",
    "make_asset_id", "make_config_hash", "make_table_name",
    "DataLayerManager", "LayerFingerprint", "LayerStatus",
    "check_data_layers", "print_data_layer_report",
]
