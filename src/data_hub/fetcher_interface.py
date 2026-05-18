"""
数据源抽象接口 -- 定义统一的数据获取协议

所有数据源实现必须遵守此接口，保证 run_downloader 可以无感切换。
"""

from abc import ABC, abstractmethod

import pandas as pd


class AbstractDataFetcher(ABC):
    """数据获取器抽象基类

    子类必须实现 fetch_single()，返回统一格式的 DataFrame，
    包含 OHLCV + 因子列。失败返回 None。
    """

    @abstractmethod
    def fetch_single(self, code: str, start_date: str, end_date: str) -> pd.DataFrame | None:
        """获取单只股票的日线数据

        Parameters
        ----------
        code : str
            股票代码，格式如 "sh.600000" / "sz.000001"
        start_date : str
            起始日期 "YYYY-MM-DD"
        end_date : str
            截止日期 "YYYY-MM-DD"

        Returns
        -------
        pd.DataFrame | None
            统一格式的日线数据，至少包含:
            date, code, open, high, low, close, volume, amount,
            pctChg, isST, tradestatus, turn, peTTM, pbMRQ, psTTM, pcfNcfTTM,
            cum_factor, fwd_factor, bwd_factor, corp_action_flag,
            factor_source, factor_updated_at
            失败或无数据时返回 None。
        """
        ...
