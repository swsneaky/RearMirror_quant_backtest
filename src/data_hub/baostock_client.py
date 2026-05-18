"""
BaoStock 客户端 -- 历史成份股 + 日线下载
铁律三：落盘 Parquet + sort_values + float32
"""
import json
import logging
import os
import time
import random
import gc

import baostock as bs
import pandas as pd

from src.config_loader import load_config
from src.data_hub.akshare_client import fetch_industry_mapping
from src.data_hub.source_manager import DataSourceManager

logger = logging.getLogger(__name__)


def _recompute_cum_factor(df: pd.DataFrame, pct_col: str = "pctChg") -> pd.DataFrame:
    """Rebuild the cumulative return proxy from the full per-stock history."""
    if pct_col not in df.columns:
        return df

    df = df.sort_values("date").reset_index(drop=True)
    ret = pd.to_numeric(df[pct_col], errors="coerce").fillna(0.0) / 100.0
    df["ret"] = ret
    df["cum_factor"] = (1.0 + ret).cumprod()
    return df


def _fetch_adjusted_close(
    code: str,
    start_date: str,
    end_date: str,
    adjustflag: str,
) -> pd.DataFrame:
    """Fetch adjusted close series and return [date, close_adj]."""
    rs = bs.query_history_k_data_plus(
        code,
        "date,close",
        start_date=start_date,
        end_date=end_date,
        frequency="d",
        adjustflag=adjustflag,
    )
    rows: list[list[str]] = []
    while rs.next():
        rows.append(rs.get_row_data())
    if not rows:
        return pd.DataFrame(columns=["date", "close_adj"])
    out = pd.DataFrame(rows, columns=["date", "close_adj"])
    out["date"] = pd.to_datetime(out["date"])
    out["close_adj"] = pd.to_numeric(out["close_adj"], errors="coerce")
    return out


def get_historical_universe(cfg: dict) -> list[str]:
    """通过 BaoStock 按半年采样历史成员（支持多指数）"""
    etl = cfg["etl"]
    index_name = etl.get("index_name", "zz500")
    _INDEX_LABEL = {"zz500": "中证 500", "hs300": "沪深 300", "sz50": "上证 50"}
    label = _INDEX_LABEL.get(index_name, index_name)
    print(f"[FIND] 正在查询 [{label}] 历史成份股名单...")
    bs.login()

    # 指数查询函数映射
    _index_query = {
        "zz500":  bs.query_zz500_stocks,
        "hs300":  bs.query_hs300_stocks,
        "sz50":   bs.query_sz50_stocks,
    }
    query_fn = _index_query.get(index_name)
    if query_fn is None:
        bs.logout()
        raise ValueError(
            f"不支持的 index_name: '{index_name}'，可选: {list(_index_query.keys())}"
        )

    sample_dates = (
        pd.date_range(start=etl["start_date"], end=etl["end_date"], freq=etl["sample_freq"])
        .strftime("%Y-%m-%d")
        .tolist()
    )
    sample_dates.append(etl["end_date"])

    all_codes: set[str] = set()
    for i, d in enumerate(sample_dates):
        print(f"  [DATE] [{i+1}/{len(sample_dates)}] 检查 {d} 的成份股...", end="")
        rs = query_fn(date=d)
        count = 0
        while (rs.error_code == "0") & rs.next():
            all_codes.add(rs.get_row_data()[1])
            count += 1
        print(f" {count} 只 (累计去重 {len(all_codes)})")

    bs.logout()
    final = sorted(all_codes)
    print(f"[OK] 成份股查询完成！{etl['start_date']}~{etl['end_date']} 间共 {len(final)} 只股票曾入围 {label}。")
    return final


def _fetch_single_stock(code: str, cfg: dict, start_date: str | None = None, end_date: str | None = None) -> pd.DataFrame | None:
    etl = cfg["etl"]
    sd = start_date or etl["start_date"]
    ed = end_date or etl["end_date"]
    # tradestatus: 1=正常交易, 0=停牌
    # turn: 换手率(%), peTTM: 滚动市盈率, pbMRQ: 市净率, psTTM: 滚动市销率, pcfNcfTTM: 滚动市现率
    fields = ("date,code,open,high,low,close,volume,amount,pctChg,isST,tradestatus,"
              "turn,peTTM,pbMRQ,psTTM,pcfNcfTTM")
    rs = bs.query_history_k_data_plus(
        code, fields,
        start_date=sd,
        end_date=ed,
        frequency="d",
        adjustflag="2",
    )
    rows = []
    while rs.next():
        rows.append(rs.get_row_data())
    if not rows:
        return None

    df = pd.DataFrame(rows, columns=fields.split(","))
    num_cols = ["open", "high", "low", "close", "volume", "amount", "pctChg",
                "turn", "peTTM", "pbMRQ", "psTTM", "pcfNcfTTM"]
    df[num_cols] = df[num_cols].apply(pd.to_numeric, errors="coerce")
    df["tradestatus"] = pd.to_numeric(df["tradestatus"], errors="coerce").fillna(0).astype(int)
    df["isST"] = pd.to_numeric(df["isST"], errors="coerce").fillna(0).astype(int)
    df["date"] = pd.to_datetime(df["date"])
    df = _recompute_cum_factor(df)

    # adjustflag="2" returns forward-adjusted OHLC directly; no separate factor
    # computation needed. Factor columns are set to identity.
    df["fwd_factor"] = 1.0
    df["bwd_factor"] = 1.0
    df["corp_action_flag"] = 0
    df["factor_source"] = "baostock_direct_adjusted"
    df["factor_updated_at"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")

    return df


def run_downloader(cfg: dict) -> None:
    """下载引擎 (支持增量/全量 + 断点续传 + 反爬)"""
    etl = cfg["etl"]
    ac = etl["anti_crawl"]
    cache_dir = etl["cache_dir"]
    update_mode = etl.get("update_mode", "incremental")
    os.makedirs(cache_dir, exist_ok=True)

    # ── 数据源选择 ──
    src_mgr = DataSourceManager(cfg)
    fetcher = src_mgr.get_fetcher()
    print(f"[SOURCE] 当前数据源: {src_mgr.current_source}")

    # 增量模式：自动用今天作为下载截止日，确保拉到最新数据
    if update_mode == "incremental":
        today_str = pd.Timestamp.now().strftime("%Y-%m-%d")
        end_date = max(etl["end_date"], today_str)
        if end_date != etl["end_date"]:
            print(f"[DATE] 增量模式：下载截止日自动延伸 {etl['end_date']} -> {end_date}")
    else:
        end_date = etl["end_date"]

    # ── 成份股名单缓存：有效则直接复用，无需每次查询 ──
    universe_path = os.path.join(cache_dir, "_universe.json")
    meta_path = os.path.join(cache_dir, "_universe_meta.json")
    current_meta = {
        "index_name": etl.get("index_name", "zz500"),
        "start_date": etl["start_date"],
        "end_date": etl["end_date"],
    }

    universe = None
    if os.path.exists(universe_path) and os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            saved_meta = json.load(f)
        if saved_meta == current_meta:
            with open(universe_path, "r", encoding="utf-8") as f:
                universe = json.load(f)
            print(f"[LIST] 成份股名单已缓存 ({len(universe)} 只)，跳过查询。")

    if universe is None:
        universe = get_historical_universe(cfg)
        if not universe:
            print("[FAIL] 未获取到名单")
            return
        # 持久化名单 + 元数据
        with open(universe_path, "w", encoding="utf-8") as f:
            json.dump(universe, f, ensure_ascii=False)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(current_meta, f, ensure_ascii=False)

    # ── 行业映射：跟成份股名单一起管理，文件不存在时自动抓取 ──
    industry_path = etl.get("industry_map", "")
    if industry_path and not os.path.exists(industry_path):
        print("[FACT] 行业映射文件不存在，自动抓取...")
        try:
            fetch_industry_mapping(cfg)
        except Exception as exc:
            logger.warning("行业映射抓取失败（可忽略，不影响下载）: %s", exc)
            print(f"[WARN] 行业映射抓取失败: {exc}")
    else:
        if industry_path:
            print(f"[LIST] 行业映射已就绪: {industry_path}")

    max_stocks = etl.get("max_stocks", 0)
    if max_stocks > 0:
        universe = universe[:max_stocks]
        print(f"[WARN] 测试模式：只下载前 {max_stocks} 只股票")

    # ── 缓存扫描：区分 全新 / 需增量 / 已最新 ──
    new_codes: list[str] = []          # 没有缓存，需全量拉取
    incr_codes: list[tuple[str, str]] = []  # (code, last_date_str)，需增量
    uptodate: list[str] = []           # 已最新，跳过

    end_dt = pd.Timestamp(end_date)
    for code in universe:
        fp = os.path.join(cache_dir, f"{code}.parquet")
        if not os.path.exists(fp):
            new_codes.append(code)
            continue
        if update_mode == "full":
            # 全量模式忽略旧缓存
            new_codes.append(code)
            continue
        # 增量：读取缓存最后日期
        try:
            cached_df = pd.read_parquet(fp, columns=["date"])
            last_date = pd.to_datetime(cached_df["date"]).max()
            if last_date >= end_dt:
                uptodate.append(code)
            else:
                # 从 last_date 的下一天开始拉
                next_day = (last_date + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
                incr_codes.append((code, next_day))
        except Exception:
            new_codes.append(code)

    total = len(universe)
    n_up = len(uptodate)
    n_new = len(new_codes)
    n_incr = len(incr_codes)
    n_todo = n_new + n_incr
    print(f"\n{'='*50}")
    print(f"[STAT] 下载计划 (模式: {update_mode})")
    print(f"   总计: {total} 只 | 已最新(跳过): {n_up} 只")
    print(f"   全新下载: {n_new} 只 | 增量更新: {n_incr} 只")
    print(f"{'='*50}")

    if n_todo == 0:
        print("[OK] 所有股票已是最新，无需下载。")
        return

    bs.login()
    failed_codes = []
    downloaded = 0
    incremented = 0

    # 合并任务列表: (code, start_date_or_None, is_incremental)
    tasks: list[tuple[str, str | None, bool]] = []
    for code in new_codes:
        tasks.append((code, None, False))
    for code, start_d in incr_codes:
        tasks.append((code, start_d, True))

    for i, (code, start_d, is_incr) in enumerate(tasks):
        fp = os.path.join(cache_dir, f"{code}.parquet")
        overall = n_up + i + 1
        tag = "增量" if is_incr else "全新"
        print(f"  [LOAD] [{i+1}/{n_todo}] (总进度 {overall}/{total}) [{tag}] {code} ...", end=" ")

        retry = 0
        success = False
        while retry < ac["max_retry"]:
            try:
                df = fetcher.fetch_single(code, start_date=start_d, end_date=end_date)
                if df is not None and not df.empty:
                    if is_incr:
                        # 追加到已有缓存
                        old_df = pd.read_parquet(fp)
                        old_df["date"] = pd.to_datetime(old_df["date"])
                        merged = pd.concat([old_df, df], ignore_index=True)
                        merged = merged.drop_duplicates(subset=["date"], keep="last")
                        merged = _recompute_cum_factor(merged)
                        for col in ["fwd_factor", "bwd_factor"]:
                            if col not in merged.columns:
                                merged[col] = 1.0
                            merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(1.0)
                        if "corp_action_flag" not in merged.columns:
                            merged["corp_action_flag"] = 0
                        merged["corp_action_flag"] = (
                            pd.to_numeric(merged["corp_action_flag"], errors="coerce")
                            .fillna(0)
                            .astype(int)
                        )
                        if "factor_source" not in merged.columns:
                            merged["factor_source"] = "baostock_adjustflag_2_only"
                        if "factor_updated_at" not in merged.columns:
                            merged["factor_updated_at"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
                        merged.to_parquet(fp, index=False)
                    else:
                        df.to_parquet(fp, index=False)
                elif not is_incr:
                    # 全新下载但无数据 -- 仍视为成功(退市股等)
                    pass
                success = True
                break
            except Exception as exc:
                retry += 1
                logger.warning("股票 %s 下载失败 (retry %d/%d): %s", code, retry, ac["max_retry"], exc)
                time.sleep(2)
                bs.login()

        if success:
            rows = len(df) if df is not None else 0
            if is_incr:
                incremented += 1
            else:
                downloaded += 1
            print(f"[OK] (+{rows}行)")
        else:
            failed_codes.append(code)
            logger.warning("股票 %s 重试耗尽，已跳过", code)
            print("[FAIL] 失败")

        time.sleep(random.uniform(*ac["sleep_per_stock"]))
        if (i + 1) % ac["checkpoint_every"] == 0:
            bs.logout()
            print(f"  [WAIT] checkpoint 休息中... (已完成 {i+1}/{n_todo})")
            time.sleep(random.uniform(*ac["checkpoint_sleep"]))
            bs.login()

    bs.logout()
    gc.collect()

    # ── 下载摘要 ──
    print(f"\n{'='*50}")
    print(f"[LIST] 下载完成摘要")
    print(f"   全新下载: {downloaded} 只 | 增量更新: {incremented} 只 | 跳过(已最新): {n_up} 只 | 失败: {len(failed_codes)} 只")
    if failed_codes:
        logger.warning("日线下载完成，但 %d 只股票失败: %s", len(failed_codes), failed_codes[:20])
        print(f"   [FAIL] 失败列表: {failed_codes[:20]}")
    print(f"{'='*50}")


def download_benchmark_index(cfg: dict) -> pd.DataFrame:
    """下载基准指数日线 (收盘价 + pctChg)，用于回测基准对比"""
    etl = cfg["etl"]
    bt = cfg.get("backtest", {})
    bench_code = bt.get("benchmark_code", "sh.000905")  # 默认中证500
    # 文件名包含指数代码，避免不同基准互相覆盖
    safe_code = bench_code.replace(".", "_")
    bench_path = os.path.join(etl.get("cache_dir", "data"), f"benchmark_{safe_code}.parquet")

    if os.path.exists(bench_path):
        print(f"[STAT] 基准指数已缓存: {bench_path}")
        return pd.read_parquet(bench_path)

    print(f"[STAT] 正在下载基准指数 {bench_code} ...")
    bs.login()
    rs = bs.query_history_k_data_plus(
        bench_code,
        "date,code,close,pctChg",
        start_date=etl["start_date"],
        end_date=etl["end_date"],
        frequency="d",
    )
    rows = []
    while rs.next():
        rows.append(rs.get_row_data())
    bs.logout()

    if not rows:
        print("[WARN]  基准指数下载失败，回测将使用等权基准")
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=["date", "code", "close", "pctChg"])
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["pctChg"] = pd.to_numeric(df["pctChg"], errors="coerce") / 100  # 百分比->小数
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    os.makedirs(os.path.dirname(bench_path) or ".", exist_ok=True)
    df.to_parquet(bench_path, index=False, engine="pyarrow")
    print(f"[OK] 基准指数已缓存: {bench_path} ({len(df)} 行)")
    return df
