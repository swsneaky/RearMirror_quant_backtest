"""AkShare 客户端 -- 行业映射表抓取（东财 API + CSV 降级）"""
import logging
import os
import time

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)

# CSV 降级路径：根目录曾由 notebook 手动生成
_CSV_FALLBACK = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "stock_industry_map.csv")
)


def fetch_industry_mapping(cfg: dict) -> pd.DataFrame:
    """抓取东财申万行业对应关系，API 失败时自动降级读取本地 CSV"""
    out_path = cfg["etl"]["industry_map"]
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    try:
        result = _fetch_from_eastmoney()
    except Exception as exc:
        logger.warning("东财 API 抓取失败: %s，尝试 CSV 降级...", exc)
        print(f"[WARN] 东财 API 不可用: {exc}")
        result = _fallback_csv()

    result.to_parquet(out_path, index=False, engine="pyarrow")
    print(f"[OK] 行业映射已保存: {out_path} ({len(result)} 条)")
    return result


def _fetch_from_eastmoney() -> pd.DataFrame:
    """从东财 API 在线抓取"""
    print("[WEB] 正在从东财抓取行业映射...")
    df_list = ak.stock_board_industry_name_em()
    mapping = []
    skipped = []
    for _, row in df_list.iterrows():
        ind_name = row["板块名称"]
        try:
            stocks = ak.stock_board_industry_cons_em(symbol=ind_name)
            tmp = stocks[["代码"]].copy()
            tmp["industry"] = ind_name
            mapping.append(tmp)
        except Exception as exc:
            skipped.append(ind_name)
            logger.warning("行业 [%s] 抓取失败，已跳过: %s", ind_name, exc)
            continue
        time.sleep(0.1)

    if skipped:
        logger.warning("共 %d 个行业抓取失败: %s", len(skipped), skipped)

    full = pd.concat(mapping).drop_duplicates(subset=["代码"])
    full["code"] = full["代码"].apply(lambda c: f"{'sh' if c.startswith('60') else 'sz'}.{c}")
    return full[["code", "industry"]]


def _fallback_csv() -> pd.DataFrame:
    """降级：读取根目录 stock_industry_map.csv"""
    if not os.path.exists(_CSV_FALLBACK):
        raise FileNotFoundError(f"CSV 降级文件也不存在: {_CSV_FALLBACK}")
    print(f"[DIR] 降级读取本地 CSV: {_CSV_FALLBACK}")
    df = pd.read_csv(_CSV_FALLBACK)
    if "code" not in df.columns or "industry" not in df.columns:
        raise ValueError(f"CSV 格式不正确，需要 code/industry 列，实际: {df.columns.tolist()}")
    return df[["code", "industry"]]


def fetch_stock_info(cfg: dict, codes: list[str] | None = None) -> pd.DataFrame:
    """
    从 AKShare 获取股票基本信息（名称、上市日期等）。

    Parameters
    ----------
    cfg : 配置字典
    codes : 可选，只获取指定代码的信息。None 表示获取全部 A 股。

    Returns
    -------
    DataFrame with columns: code, name, industry, list_date, market
    """
    logger.info("正在从 AKShare 获取股票信息...")

    try:
        # 获取 A 股列表
        df = ak.stock_info_a_code_name()
        # 列: code, name (code 是 6 位数字字符串)

        result = []
        for _, row in df.iterrows():
            code_raw = str(row["code"])
            # 转换为 sh.600000 / sz.000001 格式
            if code_raw.startswith("60") or code_raw.startswith("68"):
                code = f"sh.{code_raw}"
                market = "sh"
            else:
                code = f"sz.{code_raw}"
                market = "sz"

            # 如果指定了 codes 列表，只处理这些
            if codes and code not in codes:
                continue

            result.append({
                "code": code,
                "name": row.get("name", ""),
                "industry": "",  # 行业需要单独获取或从 industry_map 关联
                "list_date": "",
                "market": market,
            })

        info_df = pd.DataFrame(result)

        # 关联行业信息
        try:
            industry_df = fetch_industry_mapping(cfg) if os.path.exists(cfg.get("et", {}).get("industry_map", "")) else pd.DataFrame()
            if not industry_df.empty:
                info_df = info_df.merge(industry_df, on="code", how="left", suffixes=("", "_y"))
                if "industry_y" in info_df.columns:
                    info_df["industry"] = info_df["industry_y"].fillna(info_df["industry"])
                    info_df.drop(columns=["industry_y"], inplace=True)
        except Exception as e:
            logger.warning(f"关联行业信息失败: {e}")

        logger.info(f"获取到 {len(info_df)} 只股票信息")
        return info_df

    except Exception as e:
        logger.error(f"获取股票信息失败: {e}")
        raise


def fetch_stock_names(codes: list[str]) -> dict[str, str]:
    """
    从 AKShare 获取股票名称映射。

    Parameters
    ----------
    codes : 股票代码列表，格式为 sh.600000 / sz.000001

    Returns
    -------
    字典 {code: name}
    """
    if not codes:
        return {}

    logger.info(f"正在获取 {len(codes)} 只股票的名称...")

    try:
        df = ak.stock_info_a_code_name()
        name_map = {}

        for _, row in df.iterrows():
            code_raw = str(row["code"])
            # 转换格式
            if code_raw.startswith("60") or code_raw.startswith("68"):
                code = f"sh.{code_raw}"
            else:
                code = f"sz.{code_raw}"

            if code in codes:
                name_map[code] = row.get("name", "")

        logger.info(f"成功获取 {len(name_map)} 只股票名称")
        return name_map

    except Exception as e:
        logger.error(f"获取股票名称失败: {e}")
        return {}
