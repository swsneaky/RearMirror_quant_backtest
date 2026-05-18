"""
AkShare 数据获取器 -- 通过 ak.stock_zh_a_hist() 获取 A 股前复权日线

akshare 原生不提供估值字段 (peTTM/pbMRQ/psTTM/pcfNcfTTM) 和
ST/交易状态标记，这些列统一填 NaN/0。etl_process.py 已有容错处理。
"""

import logging

import pandas as pd

from src.data_hub.fetcher_interface import AbstractDataFetcher

logger = logging.getLogger(__name__)

# akshare 中文列名 -> 标准列名 映射
_COLUMN_MAP = {
    "日期": "date",
    "股票代码": "ak_code",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
    "涨跌幅": "pctChg",
    "换手率": "turn",
}


class AkShareFetcher(AbstractDataFetcher):
    """AkShare 前复权日线获取器

    调用 ak.stock_zh_a_hist(adjust="qfq")，做字段映射和列补齐。
    akshare 缺失的估值字段 (peTTM/pbMRQ/psTTM/pcfNcfTTM) 填 NaN，
    isST=0, tradestatus=1。
    """

    def fetch_single(self, code: str, start_date: str, end_date: str) -> pd.DataFrame | None:
        import akshare as ak

        # 去掉 sh./sz. 前缀，得到纯数字代码如 "600000"
        symbol = code.replace("sh.", "").replace("sz.", "")

        # akshare 需要 YYYYMMDD 格式
        sd = start_date.replace("-", "")
        ed = end_date.replace("-", "")

        try:
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=sd,
                end_date=ed,
                adjust="qfq",
            )
        except Exception as exc:
            logger.warning("akshare fetch failed for %s: %s", code, exc)
            return None

        if df is None or df.empty:
            return None

        # ---- 字段映射 ----
        # 只保留映射表中存在的列
        cols = [c for c in _COLUMN_MAP if c in df.columns]
        df_out = df[cols].rename(columns=_COLUMN_MAP)

        # 恢复带前缀的 code
        df_out["code"] = code

        # ---- 类型转换 ----
        df_out["date"] = pd.to_datetime(df_out["date"])
        numeric_cols = ["open", "high", "low", "close", "volume", "amount", "pctChg", "turn"]
        for c in numeric_cols:
            if c in df_out.columns:
                df_out[c] = pd.to_numeric(df_out[c], errors="coerce")

        # ---- 补缺失列 ----
        df_out["isST"] = 0
        df_out["tradestatus"] = 1
        df_out["peTTM"] = float("nan")
        df_out["pbMRQ"] = float("nan")
        df_out["psTTM"] = float("nan")
        df_out["pcfNcfTTM"] = float("nan")

        # ---- 因子列 ----
        df_out["fwd_factor"] = 1.0
        df_out["bwd_factor"] = 1.0
        df_out["corp_action_flag"] = 0
        df_out["factor_source"] = "akshare_qfq"
        df_out["factor_updated_at"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")

        # ---- 计算 cum_factor ----
        df_out = df_out.sort_values("date").reset_index(drop=True)
        ret = pd.to_numeric(df_out["pctChg"], errors="coerce").fillna(0.0) / 100.0
        df_out["cum_factor"] = (1.0 + ret).cumprod()

        # ---- 整理列顺序（与 baostock 输出对齐） ----
        ordered = [
            "date", "code", "open", "high", "low", "close", "volume", "amount",
            "pctChg", "isST", "tradestatus", "turn",
            "peTTM", "pbMRQ", "psTTM", "pcfNcfTTM",
            "cum_factor", "fwd_factor", "bwd_factor", "corp_action_flag",
            "factor_source", "factor_updated_at",
        ]
        df_out = df_out[[c for c in ordered if c in df_out.columns]]

        return df_out
