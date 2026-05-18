"""
数据源管理器 -- 根据配置和健康检查自动选择数据源

支持三种模式:
- "baostock": 强制使用 BaoStock
- "akshare":  强制使用 AkShare
- "auto":     健康检查 baostock，可用则用，不可用则 fallback 到 akshare
"""

import logging
import socket
import time

from src.data_hub.baostock_fetcher import BaoStockFetcher
from src.data_hub.akshare_fetcher import AkShareFetcher
from src.data_hub.fetcher_interface import AbstractDataFetcher

logger = logging.getLogger(__name__)

_BAOSTOCK_HOST = "www.baostock.com"
_BAOSTOCK_PORT = 10030
_HEALTH_TIMEOUT = 5  # TCP 连接超时 (秒)


class DataSourceManager:
    """统一管理数据源的选择与健康检查"""

    def __init__(self, cfg: dict):
        etl = cfg.get("etl", {})
        self.source_setting = etl.get("data_source", "auto")
        self.baostock_fetcher = BaoStockFetcher(cfg)
        self.akshare_fetcher = AkShareFetcher()
        self.current_source: str = ""  # 实际生效的数据源名称

    def get_fetcher(self) -> AbstractDataFetcher:
        """根据配置和健康检查返回当前可用的 fetcher"""
        if self.source_setting == "baostock":
            self.current_source = "baostock"
            return self.baostock_fetcher

        if self.source_setting == "akshare":
            self.current_source = "akshare"
            return self.akshare_fetcher

        # auto 模式：先检查 baostock 是否可达
        if self.source_setting == "auto":
            if self.check_baostock_health():
                self.current_source = "baostock"
                print("[SOURCE] baostock 可达，使用 BaoStock 数据源")
                return self.baostock_fetcher
            else:
                self.current_source = "akshare"
                print("[SOURCE] baostock 不可达，回退到 AkShare 数据源")
                return self.akshare_fetcher

        # 未知值：fallback 到 baostock
        logger.warning("未知 data_source 值 '%s'，使用 baostock", self.source_setting)
        self.current_source = "baostock"
        return self.baostock_fetcher

    @staticmethod
    def check_baostock_health() -> bool:
        """TCP 连接检测 baostock 数据端口是否可达

        Returns
        -------
        bool
            True 表示 baostock 数据服务可达
        """
        try:
            with socket.create_connection(
                (_BAOSTOCK_HOST, _BAOSTOCK_PORT),
                timeout=_HEALTH_TIMEOUT,
            ):
                return True
        except (socket.timeout, socket.error, OSError):
            return False
