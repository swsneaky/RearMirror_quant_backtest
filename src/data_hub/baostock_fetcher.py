"""
BaoStock 数据获取器 -- 封装现有 _fetch_single_stock() 为 AbstractDataFetcher 实现

不修改 baostock_client.py 任何代码。
bs.login() / bs.logout() 由 run_downloader 外层管理，此 fetcher 内部不调用。
"""

import pandas as pd

from src.data_hub.fetcher_interface import AbstractDataFetcher


class BaoStockFetcher(AbstractDataFetcher):
    """BaoStock 数据获取器

    内部复用 baostock_client._fetch_single_stock()，
    通过构造函数注入 cfg 配置字典。
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def fetch_single(self, code: str, start_date: str, end_date: str) -> pd.DataFrame | None:
        from src.data_hub.baostock_client import _fetch_single_stock
        return _fetch_single_stock(code, self.cfg, start_date=start_date, end_date=end_date)
