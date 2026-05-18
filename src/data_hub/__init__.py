"""
数据中枢 -- 统一调度数据抓取与 ETL
"""
from src.data_hub.baostock_client import get_historical_universe, run_downloader, download_benchmark_index  # noqa: F401
from src.data_hub.akshare_client import fetch_industry_mapping  # noqa: F401
from src.data_hub.etl_process import merge_and_clean  # noqa: F401
