"""
股票数据 API

端点:
  GET  /api/stocks           -- 股票列表（分页、筛选）
  GET  /api/stocks/stats     -- 本地股票统计
  GET  /api/stocks/{code}    -- 单只股票详情
  GET  /api/stocks/{code}/ohlc -- K线数据
  POST /api/stocks/sync-names -- 同步股票名称
  POST /api/stocks/update    -- 增量更新股票数据
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel

from src.config_loader import load_config
from src.data_layer.db import get_connection

router = APIRouter(prefix="/api/stocks", tags=["stocks"])
logger = logging.getLogger(__name__)


# ================================================================
# 缓存刷新
# ================================================================
def _refresh_stock_latest_cache(cfg: dict) -> int:
    """
    刷新 stock_latest 缓存表

    从 daily_bar 聚合每只股票的最新数据，存入缓存表。
    返回缓存的股票数量。
    """
    con = get_connection(cfg)

    # 删除旧数据
    con.execute("DELETE FROM stock_latest")

    # 使用子查询获取每只股票最新日期的行数据
    # 先获取每只股票的最新日期，再 JOIN 回原表获取该行的其他数据
    con.execute("""
        INSERT INTO stock_latest
            (code, latest_date, raw_close, raw_pctChg, raw_volume, raw_amount,
             raw_turn, raw_peTTM, raw_pbMRQ, isST, bar_count)
        SELECT
            db.code,
            db.date as latest_date,
            db.raw_close,
            db.raw_pctChg,
            db.raw_volume,
            db.raw_amount,
            db.raw_turn,
            db.raw_peTTM,
            db.raw_pbMRQ,
            db.isST,
            cnt.bar_count
        FROM daily_bar db
        INNER JOIN (
            SELECT code, MAX(date) as max_date
            FROM daily_bar
            GROUP BY code
        ) latest ON db.code = latest.code AND db.date = latest.max_date
        INNER JOIN (
            SELECT code, COUNT(*) as bar_count
            FROM daily_bar
            GROUP BY code
        ) cnt ON db.code = cnt.code
    """)

    # 获取插入数量
    result = con.execute("SELECT COUNT(*) FROM stock_latest").fetchone()
    count = result[0] if result else 0
    logger.info(f"stock_latest 缓存已刷新，共 {count} 只股票")
    return count


# ================================================================
# 响应模型
# ================================================================
class StockListItem(BaseModel):
    """股票列表项"""
    code: str
    name: str | None
    industry: str | None
    latest_date: str | None
    latest_close: float | None
    pct_chg: float | None
    volume: float | None
    amount: float | None
    turn: float | None
    pe_ttm: float | None
    pb_mrq: float | None
    is_st: bool
    is_delisted: bool = False
    bar_count: int


class StockListResponse(BaseModel):
    """股票列表响应"""
    stocks: list[StockListItem]
    total: int
    page: int
    page_size: int


class StockStats(BaseModel):
    """股票统计"""
    total_stocks: int
    with_names: int
    by_industry: dict[str, int]
    date_range: tuple[str, str] | None
    total_bars: int


class StockDetail(BaseModel):
    """股票详情"""
    code: str
    name: str | None
    industry: str | None
    latest_date: str | None
    latest_close: float | None
    pct_chg: float | None
    volume: float | None
    amount: float | None
    turn: float | None
    pe_ttm: float | None
    pb_mrq: float | None
    ps_ttm: float | None
    pcf_ttm: float | None
    is_st: bool
    bar_count: int
    date_range: tuple[str, str] | None


class OHLCBar(BaseModel):
    """K线数据"""
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float
    pct_chg: float
    turn: float


class OHLCResponse(BaseModel):
    """K线数据响应"""
    code: str
    bars: list[OHLCBar]


class SyncNamesResponse(BaseModel):
    """同步名称响应"""
    success: bool
    message: str
    updated_count: int


# ================================================================
# 辅助函数
# ================================================================
def _get_stock_list_from_db(
    cfg: dict,
    page: int = 1,
    page_size: int = 50,
    search: str = "",
    industry: str = "",
    sort_by: str = "code",
    sort_desc: bool = False,
) -> tuple[list[dict], int]:
    """从数据库获取股票列表 (使用缓存表加速)"""
    con = get_connection(cfg)

    # 检查缓存表是否有数据，没有则刷新
    cache_count = con.execute("SELECT COUNT(*) FROM stock_latest").fetchone()[0]
    if cache_count == 0:
        logger.info("stock_latest 缓存为空，正在刷新...")
        _refresh_stock_latest_cache(cfg)

    # 使用缓存表查询 (快速)
    base_query = """
        SELECT
            sl.code,
            si.name,
            si.industry,
            sl.latest_date,
            sl.raw_close as latest_close,
            sl.raw_pctChg as pct_chg,
            sl.raw_volume as volume,
            sl.raw_amount as amount,
            sl.raw_turn as turn,
            sl.raw_peTTM as pe_ttm,
            sl.raw_pbMRQ as pb_mrq,
            sl.isST as is_st,
            sl.is_delisted,
            sl.bar_count
        FROM stock_latest sl
        LEFT JOIN stock_info si ON sl.code = si.code
    """

    # 构建条件
    conditions = []
    params = []

    if search:
        conditions.append("(sl.code LIKE ? OR si.name LIKE ?)")
        search_pattern = f"%{search}%"
        params.extend([search_pattern, search_pattern])

    if industry:
        conditions.append("si.industry = ?")
        params.append(industry)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    # 排序 - 映射 API 列名到数据库列名
    sort_col_map = {
        "code": "code",
        "name": "name",  # special case
        "latest_close": "raw_close",
        "pct_chg": "raw_pctChg",
        "bar_count": "bar_count",
        "turn": "raw_turn",
        "pe_ttm": "raw_peTTM",
    }
    valid_sort_cols = set(sort_col_map.keys())
    if sort_by not in valid_sort_cols:
        sort_by = "code"
    sort_dir = "DESC" if sort_desc else "ASC"

    # 对于 name 列，需要处理 NULL 值
    if sort_by == "name":
        order_clause = f"ORDER BY COALESCE(si.name, sl.code) {sort_dir}"
    else:
        db_col = sort_col_map[sort_by]
        order_clause = f"ORDER BY sl.{db_col} {sort_dir}"

    # 分页
    offset = (page - 1) * page_size
    limit_clause = f"LIMIT {page_size} OFFSET {offset}"

    # 计算总数 - 直接在主表上计数，不使用子查询
    count_query = f"""
        SELECT COUNT(*)
        FROM stock_latest sl
        LEFT JOIN stock_info si ON sl.code = si.code
        {where_clause}
    """
    total = con.execute(count_query, params).fetchone()[0]

    # 获取数据
    data_query = f"{base_query} {where_clause} {order_clause} {limit_clause}"
    rows = con.execute(data_query, params).fetchall()

    stocks = []
    for row in rows:
        stocks.append({
            "code": row[0],
            "name": row[1],
            "industry": row[2],
            "latest_date": row[3],
            "latest_close": row[4],
            "pct_chg": row[5],
            "volume": row[6],
            "amount": row[7],
            "turn": row[8],
            "pe_ttm": row[9],
            "pb_mrq": row[10],
            "is_st": bool(row[11]),
            "is_delisted": bool(row[12] or 0),
            "bar_count": row[13] or 0,
        })

    return stocks, total


def _get_industries(cfg: dict) -> list[str]:
    """获取所有行业列表"""
    con = get_connection(cfg)
    rows = con.execute("""
        SELECT DISTINCT industry FROM stock_info
        WHERE industry IS NOT NULL AND industry != ''
        ORDER BY industry
    """).fetchall()
    return [r[0] for r in rows]


# ================================================================
# 端点实现
# ================================================================
@router.get("", response_model=StockListResponse)
async def get_stocks(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    search: str = Query(""),
    industry: str = Query(""),
    sort_by: str = Query("code"),
    sort_desc: bool = Query(False),
):
    """获取股票列表"""
    cfg = load_config()
    stocks, total = _get_stock_list_from_db(
        cfg, page, page_size, search, industry, sort_by, sort_desc
    )
    return StockListResponse(
        stocks=[StockListItem(**s) for s in stocks],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/stats", response_model=StockStats)
async def get_stock_stats():
    """获取股票统计（使用缓存表加速）"""
    cfg = load_config()
    con = get_connection(cfg)

    # 检查缓存表是否有数据
    cache_count = con.execute("SELECT COUNT(*) FROM stock_latest").fetchone()[0]
    if cache_count == 0:
        logger.info("stock_latest 缓存为空，正在刷新...")
        _refresh_stock_latest_cache(cfg)

    # 总股票数 - 从缓存表获取（快速）
    total_stocks = con.execute("SELECT COUNT(*) FROM stock_latest").fetchone()[0]

    # 有名称的股票数
    with_names = con.execute("SELECT COUNT(*) FROM stock_info WHERE name IS NOT NULL AND name != ''").fetchone()[0]

    # 按行业分布 - 从缓存表 JOIN stock_info（快速）
    industry_rows = con.execute("""
        SELECT si.industry, COUNT(*)
        FROM stock_latest sl
        LEFT JOIN stock_info si ON sl.code = si.code
        GROUP BY si.industry
        ORDER BY COUNT(*) DESC
    """).fetchall()
    by_industry = {row[0] or "未分类": row[1] for row in industry_rows}

    # 日期范围 - 从缓存表获取（快速）
    date_range_row = con.execute("""
        SELECT MIN(latest_date), MAX(latest_date) FROM stock_latest
    """).fetchone()
    date_range = (date_range_row[0], date_range_row[1]) if date_range_row[0] else None

    # 总数据条数 - 从缓存表的 bar_count 汇总（快速）
    total_bars = con.execute("SELECT SUM(bar_count) FROM stock_latest").fetchone()[0] or 0

    return StockStats(
        total_stocks=total_stocks,
        with_names=with_names,
        by_industry=by_industry,
        date_range=date_range,
        total_bars=total_bars,
    )


@router.get("/industries")
async def get_industries():
    """获取行业列表"""
    cfg = load_config()
    return {"industries": _get_industries(cfg)}


@router.post("/cache/refresh")
async def refresh_cache():
    """
    手动刷新 stock_latest 缓存表

    通常不需要手动调用，系统会在以下情况自动刷新：
    - 缓存为空时首次查询
    - 增量更新完成后
    """
    cfg = load_config()
    count = _refresh_stock_latest_cache(cfg)
    return {"success": True, "message": f"缓存已刷新，共 {count} 只股票", "count": count}


@router.get("/{code}", response_model=StockDetail)
async def get_stock_detail(code: str):
    """获取单只股票详情"""
    cfg = load_config()
    con = get_connection(cfg)

    # 获取基本信息
    row = con.execute("""
        SELECT
            db.code,
            si.name,
            si.industry,
            db.latest_date,
            db.raw_close as latest_close,
            db.raw_pctChg as pct_chg,
            db.raw_volume as volume,
            db.raw_amount as amount,
            db.raw_turn as turn,
            db.raw_peTTM as pe_ttm,
            db.raw_pbMRQ as pb_mrq,
            db.raw_psTTM as ps_ttm,
            db.raw_pcfNcfTTM as pcf_ttm,
            db.isST as is_st,
            db.bar_count,
            db.min_date,
            db.max_date
        FROM (
            SELECT
                code,
                MAX(date) as latest_date,
                raw_close,
                raw_pctChg,
                raw_volume,
                raw_amount,
                raw_turn,
                raw_peTTM,
                raw_pbMRQ,
                raw_psTTM,
                raw_pcfNcfTTM,
                isST,
                COUNT(*) as bar_count,
                MIN(date) as min_date,
                MAX(date) as max_date
            FROM daily_bar
            WHERE code = ?
            GROUP BY code
        ) db
        LEFT JOIN stock_info si ON db.code = si.code
    """, [code]).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail=f"股票 {code} 不存在")

    return StockDetail(
        code=row[0],
        name=row[1],
        industry=row[2],
        latest_date=row[3],
        latest_close=row[4],
        pct_chg=row[5],
        volume=row[6],
        amount=row[7],
        turn=row[8],
        pe_ttm=row[9],
        pb_mrq=row[10],
        ps_ttm=row[11],
        pcf_ttm=row[12],
        is_st=bool(row[13]),
        bar_count=row[14] or 0,
        date_range=(row[15], row[16]) if row[15] else None,
    )


@router.get("/{code}/ohlc", response_model=OHLCResponse)
async def get_stock_ohlc(
    code: str,
    start_date: str = Query(""),
    end_date: str = Query(""),
    limit: int = Query(500, ge=1, le=5000),
):
    """获取股票K线数据"""
    cfg = load_config()
    con = get_connection(cfg)

    conditions = ["code = ?"]
    params = [code]

    if start_date:
        conditions.append("date >= ?")
        params.append(start_date)
    if end_date:
        conditions.append("date <= ?")
        params.append(end_date)

    where_clause = f"WHERE {' AND '.join(conditions)}"

    rows = con.execute(f"""
        SELECT
            date,
            raw_open as open,
            raw_high as high,
            raw_low as low,
            raw_close as close,
            raw_volume as volume,
            raw_amount as amount,
            raw_pctChg as pct_chg,
            raw_turn as turn
        FROM daily_bar
        {where_clause}
        ORDER BY date DESC
        LIMIT ?
    """, params + [limit]).fetchall()

    bars = [
        OHLCBar(
            date=row[0],
            open=row[1] or 0,
            high=row[2] or 0,
            low=row[3] or 0,
            close=row[4] or 0,
            volume=row[5] or 0,
            amount=row[6] or 0,
            pct_chg=row[7] or 0,
            turn=row[8] or 0,
        )
        for row in rows
    ]

    # 反转顺序，使日期从早到晚
    bars.reverse()

    return OHLCResponse(code=code, bars=bars)


@router.post("/sync-names", response_model=SyncNamesResponse)
async def sync_stock_names():
    """
    同步股票名称和行业分类

    1. 从 AKShare 获取全部 A 股名称
    2. 从本地 stock_industry_map.parquet 关联行业
    3. 更新到 stock_info 表
    """
    from src.data_hub.akshare_client import fetch_stock_names
    import pandas as pd

    cfg = load_config()
    con = get_connection(cfg)

    # 获取本地所有股票代码
    codes = [r[0] for r in con.execute("SELECT DISTINCT code FROM daily_bar").fetchall()]

    if not codes:
        return SyncNamesResponse(success=True, message="没有需要同步的股票", updated_count=0)

    try:
        # 1. 从 AKShare 获取名称
        name_map = fetch_stock_names(codes)

        # 2. 从本地 parquet 获取行业映射
        industry_map = {}
        industry_path = cfg.get("etl", {}).get("industry_map", "data/raw/stock_industry_map.parquet")
        if os.path.exists(industry_path):
            industry_df = pd.read_parquet(industry_path)
            industry_map = dict(zip(industry_df["code"], industry_df["industry"]))
            logger.info(f"从 {industry_path} 加载 {len(industry_map)} 条行业数据")

        # 3. 更新到数据库 (只更新 stock_info 表，不更新 daily_bar 表，因为太慢)
        updated = 0
        for code in codes:
            name = name_map.get(code)
            industry = industry_map.get(code)

            if name or industry:
                con.execute("""
                    INSERT INTO stock_info (code, name, industry, updated_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(code) DO UPDATE SET
                        name = COALESCE(?, name),
                        industry = COALESCE(?, industry),
                        updated_at = CURRENT_TIMESTAMP
                """, [code, name, industry, name, industry])
                updated += 1

        return SyncNamesResponse(
            success=True,
            message=f"成功同步 {updated} 只股票的名称和行业",
            updated_count=updated,
        )

    except Exception as e:
        logger.error(f"同步失败: {e}")
        raise HTTPException(status_code=500, detail=f"同步失败: {str(e)}")


class UpdateProgress(BaseModel):
    """更新进度"""
    success: bool
    message: str
    total_stocks: int
    updated_stocks: int
    failed_stocks: int
    skipped_stocks: int
    total_bars: int


# 全局更新状态
_update_status = {
    "running": False,
    "total": 0,
    "updated": 0,
    "failed": 0,
    "skipped": 0,
    "total_bars": 0,
    "message": "",
    "started_at": None,
}


def _run_incremental_update(cfg: dict):
    """
    后台任务：增量更新所有股票数据

    使用完整的反爬机制：
    - 随机休眠 [sleep_per_stock]
    - checkpoint 长休眠 [checkpoint_sleep]
    - 失败重试 [max_retry]
    """
    import baostock as bs
    import pandas as pd
    import random
    import time
    from datetime import timedelta
    global _update_status

    con = get_connection(cfg)
    etl = cfg.get("etl", {})
    anti_crawl = etl.get("anti_crawl", {
        "sleep_per_stock": [0.2, 0.5],
        "checkpoint_every": 20,
        "checkpoint_sleep": [5.0, 10.0],
        "max_retry": 3,
    })

    # 获取所有股票的最后日期
    rows = con.execute("""
        SELECT code, MAX(date) as last_date
        FROM daily_bar
        GROUP BY code
    """).fetchall()

    code_last_date = {r[0]: r[1][:10] if r[1] else "2010-01-01" for r in rows}
    today = datetime.now().strftime("%Y-%m-%d")

    # 过滤出需要更新的股票
    need_update = []
    for code, last_date in code_last_date.items():
        if last_date < today:
            next_date = datetime.strptime(last_date, "%Y-%m-%d")
            start = (next_date + timedelta(days=1)).strftime("%Y-%m-%d")
            if start <= today:
                need_update.append((code, start))

    _update_status = {
        "running": True,
        "total": len(code_last_date),
        "updated": 0,
        "failed": 0,
        "skipped": len(code_last_date) - len(need_update),
        "total_bars": 0,
        "message": f"正在连接 BaoStock... (需更新 {len(need_update)} 只)",
        "started_at": datetime.now().isoformat(),
    }

    if not need_update:
        _update_status["running"] = False
        _update_status["message"] = "所有股票已是最新，无需更新"
        return

    fields = ("date,code,open,high,low,close,volume,amount,pctChg,isST,tradestatus,"
              "turn,peTTM,pbMRQ,psTTM,pcfNcfTTM")

    try:
        bs.login()

        for i, (code, start) in enumerate(need_update):
            _update_status["message"] = f"更新 {code} ({i+1}/{len(need_update)})"

            # 重试机制
            retry = 0
            max_retry = anti_crawl.get("max_retry", 3)
            success = False

            while retry < max_retry:
                try:
                    rs = bs.query_history_k_data_plus(
                        code, fields,
                        start_date=start,
                        end_date=today,
                        frequency="d",
                        adjustflag="3",
                    )

                    data_rows = []
                    while rs.next():
                        data_rows.append(rs.get_row_data())

                    if data_rows:
                        # 构建 DataFrame 并调用统一 ETL 入库
                        # 不再直接 INSERT INTO daily_bar，避免缺少 cum_factor/industry
                        df = pd.DataFrame(data_rows, columns=fields.split(","))
                        num_cols = ["open", "high", "low", "close", "volume", "amount", "pctChg",
                                    "turn", "peTTM", "pbMRQ", "psTTM", "pcfNcfTTM"]
                        df[num_cols] = df[num_cols].apply(pd.to_numeric, errors="coerce")
                        df["tradestatus"] = pd.to_numeric(df["tradestatus"], errors="coerce").fillna(0).astype(int)
                        df["isST"] = pd.to_numeric(df["isST"], errors="coerce").fillna(0).astype(int)
                        df["date"] = pd.to_datetime(df["date"])
                        df["code"] = code

                        # 调用统一 ETL 入库函数
                        from src.data_hub.etl_process import ingest_daily_bar_df
                        ingest_daily_bar_df(df, cfg)

                        _update_status["total_bars"] += len(data_rows)

                    _update_status["updated"] += 1
                    success = True
                    break

                except Exception as e:
                    retry += 1
                    logger.warning(f"更新 {code} 失败 (retry {retry}/{max_retry}): {e}")
                    if retry < max_retry:
                        time.sleep(2)
                        bs.login()

            if not success:
                _update_status["failed"] += 1
                logger.warning(f"股票 {code} 重试耗尽，已跳过")

            # 随机休眠 (反爬)
            sleep_range = anti_crawl.get("sleep_per_stock", [0.2, 0.5])
            time.sleep(random.uniform(sleep_range[0], sleep_range[1]))

            # Checkpoint 长休眠
            checkpoint_every = anti_crawl.get("checkpoint_every", 20)
            if (i + 1) % checkpoint_every == 0:
                bs.logout()
                _update_status["message"] = f"Checkpoint 休息... (已完成 {i+1}/{len(need_update)})"
                checkpoint_range = anti_crawl.get("checkpoint_sleep", [5.0, 10.0])
                time.sleep(random.uniform(checkpoint_range[0], checkpoint_range[1]))
                bs.login()

        bs.logout()

        # 刷新缓存表
        _update_status["message"] = "正在刷新缓存..."
        _refresh_stock_latest_cache(cfg)

        _update_status["running"] = False
        _update_status["message"] = f"完成！更新 {_update_status['updated']} 只，跳过 {_update_status['skipped']} 只，失败 {_update_status['failed']} 只，新增 {_update_status['total_bars']} 条数据"

    except Exception as e:
        _update_status["running"] = False
        _update_status["message"] = f"更新失败: {str(e)}"
        logger.error(f"增量更新失败: {e}")
        try:
            bs.logout()
        except:
            pass


@router.post("/update", response_model=UpdateProgress)
async def update_stock_data(background_tasks: BackgroundTasks):
    """
    增量更新股票数据

    自动检测每只股票的最后日期，只下载新增数据。
    在后台异步执行，避免阻塞。

    反爬机制：
    - 随机休眠 0.2~0.5 秒/只
    - 每 20 只股票长休眠 5~10 秒
    - 失败最多重试 3 次
    """
    global _update_status

    if _update_status["running"]:
        return UpdateProgress(
            success=False,
            message="更新正在进行中，请稍候",
            total_stocks=_update_status["total"],
            updated_stocks=_update_status["updated"],
            failed_stocks=_update_status["failed"],
            skipped_stocks=_update_status.get("skipped", 0),
            total_bars=_update_status["total_bars"],
        )

    cfg = load_config()
    background_tasks.add_task(_run_incremental_update, cfg)

    return UpdateProgress(
        success=True,
        message="更新任务已启动",
        total_stocks=0,
        updated_stocks=0,
        failed_stocks=0,
        skipped_stocks=0,
        total_bars=0,
    )


@router.get("/update/status", response_model=UpdateProgress)
async def get_update_status():
    """获取更新进度"""
    return UpdateProgress(
        success=not _update_status["running"],
        message=_update_status["message"],
        total_stocks=_update_status["total"],
        updated_stocks=_update_status["updated"],
        failed_stocks=_update_status["failed"],
        skipped_stocks=_update_status.get("skipped", 0),
        total_bars=_update_status["total_bars"],
    )
