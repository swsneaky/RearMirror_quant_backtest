"""
ETL 合并清洗 -- 将缓存的日线合并 + raw_ 前缀 + Canonical 入库 + Parquet 导出

日常主路径:
  raw cache 增量 -> 规范化校验 -> daily_bar 增量 upsert (canonical 层)
  Parquet 仅为 canonical export / rebuild snapshot，不是研究流程正式输入。

失败语义:
  canonical 入库失败 -> 阻断主流程 (抛出异常)
  Parquet 导出失败 -> warning (不影响 canonical 层)

铁律二：raw_ 前缀协议
铁律三：Parquet + sort + float32
"""
import logging
import os

import pandas as pd

logger = logging.getLogger(__name__)


def _apply_raw_prefix(df: pd.DataFrame) -> pd.DataFrame:
    """铁律二：raw_ 前缀 + 量纲修正"""
    raw_candidates = ["open", "high", "low", "close", "volume", "amount",
                      "pctChg", "turn", "peTTM", "pbMRQ", "psTTM", "pcfNcfTTM"]
    rename_map = {c: f"raw_{c}" for c in raw_candidates if c in df.columns}
    df = df.rename(columns=rename_map)
    if "raw_pctChg" in df.columns:
        df["raw_pctChg"] = df["raw_pctChg"] / 100
    return df


def _join_industry(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """将 industry_map 左连接到 DataFrame (按 code)"""
    industry_path = cfg["etl"].get("industry_map")
    if industry_path and os.path.exists(industry_path):
        ind_df = pd.read_parquet(industry_path)
        if "code" in ind_df.columns and "industry" in ind_df.columns:
            ind_df = ind_df[["code", "industry"]].drop_duplicates("code")
            if "industry" in df.columns:
                df = df.drop(columns=["industry"])
            df = df.merge(ind_df, on="code", how="left")
    return df


def _ensure_cum_factor(df: pd.DataFrame) -> pd.DataFrame:
    """Rebuild the canonical cumulative return proxy from raw_pctChg by code."""
    if "raw_pctChg" not in df.columns or "code" not in df.columns:
        return df

    df = df.sort_values(["code", "date"]).reset_index(drop=True)
    ret = pd.to_numeric(df["raw_pctChg"], errors="coerce").fillna(0.0)
    df["cum_factor"] = (1.0 + ret).groupby(df["code"]).cumprod()
    return df


def _ensure_price_factors(df: pd.DataFrame, factor_source: str = "unknown") -> pd.DataFrame:
    """
    Ensure adjustment-factor columns exist for dynamic price projection.

    If factors are absent, default to 1.0 so raw mode behavior is preserved.
    """
    if df.empty:
        return df

    out = df.copy()
    out = out.sort_values(["code", "date"]).reset_index(drop=True)

    for col in ["fwd_factor", "bwd_factor"]:
        if col not in out.columns:
            out[col] = 1.0
        out[col] = pd.to_numeric(out[col], errors="coerce").replace([float("inf"), float("-inf")], pd.NA)
        out[col] = out[col].fillna(1.0)

    if "corp_action_flag" not in out.columns:
        fwd_jump = out.groupby("code")["fwd_factor"].pct_change().abs() > 1e-8
        out["corp_action_flag"] = fwd_jump.fillna(False).astype(int)
    else:
        out["corp_action_flag"] = pd.to_numeric(out["corp_action_flag"], errors="coerce").fillna(0).astype(int)

    if "factor_source" not in out.columns:
        out["factor_source"] = factor_source
    out["factor_source"] = out["factor_source"].fillna(factor_source).astype(str)

    if "factor_updated_at" not in out.columns:
        out["factor_updated_at"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    out["factor_updated_at"] = out["factor_updated_at"].fillna(
        pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    )

    return out


def merge_and_clean(cfg: dict) -> pd.DataFrame:
    """
    合并 stock_daily_cache/ 下所有 parquet 并添加 raw_ 前缀。

    日常主路径:
      1. 扫描 raw cache -> 合并 -> 规范化 (raw_ 前缀 + 行业映射)
      2. 按主键增量 upsert 到 canonical daily_bar (必须成功，否则阻断)
      3. 导出 Parquet 快照 (副产物，失败不阻断)
    """
    etl = cfg["etl"]
    cache_dir = etl["cache_dir"]
    update_mode = etl.get("update_mode", "incremental")

    print(f"[PKG] 正在合并日线 (模式: {update_mode})...")
    all_files = [os.path.join(cache_dir, f) for f in os.listdir(cache_dir)
                 if f.endswith(".parquet") and not f.startswith("_")]
    if not all_files:
        raise FileNotFoundError(f"cache_dir 为空: {cache_dir}")

    final_df = pd.concat([pd.read_parquet(f) for f in all_files], ignore_index=True)
    final_df["code"] = final_df["code"].astype(str).astype(object)
    final_df["date"] = pd.to_datetime(final_df["date"])

    final_df = _apply_raw_prefix(final_df)
    final_df = _join_industry(final_df, cfg)

    # 铁律三：排序
    final_df = final_df.sort_values(["code", "date"]).reset_index(drop=True)
    final_df = _ensure_cum_factor(final_df)
    final_df = _ensure_price_factors(final_df, factor_source="etl_default")

    # --------------------------------------------------
    # Canonical 入库 (主路径，失败即阻断)
    # --------------------------------------------------
    _ingest_to_db(final_df, cfg, update_mode)

    # --------------------------------------------------
    # 入库后对账 (raw vs daily_bar，不一致即阻断)
    # --------------------------------------------------
    _reconcile_raw_db(final_df, cfg)

    # --------------------------------------------------
    # Parquet 导出 (副产物，失败不阻断)
    # --------------------------------------------------
    try:
        os.makedirs(os.path.dirname(etl["raw_output"]), exist_ok=True)
        final_df.to_parquet(etl["raw_output"], index=False, engine="pyarrow")
        print(f"[SAVE] canonical 快照导出: {etl['raw_output']} ({len(final_df):,} 行)")
    except Exception as exc:
        logger.warning("Parquet 快照导出失败 (不影响 canonical 层): %s", exc)

    # 缓存指纹 (旧版，保留兼容)
    try:
        from src.storage_manager import save_fingerprint
        save_fingerprint(
            etl["raw_output"], cfg, sections=["etl"],
            row_count=len(final_df),
            extra={"n_stocks": int(final_df["code"].nunique()), "n_cols": final_df.shape[1]},
        )
    except Exception as exc:
        logger.warning("ETL 指纹保存失败 (不影响主流程): %s", exc)

    # v3: 数据层依赖指纹 (Layer 1: canonical)
    try:
        from src.data_layer.layer_manager import DataLayerManager
        mgr = DataLayerManager(cfg)
        mgr.save_canonical_fingerprint(
            row_count=len(final_df),
            n_stocks=int(final_df["code"].nunique()),
        )
        logger.info("[LayerManager] Layer 1 (canonical) 指纹已保存")
    except Exception as exc:
        logger.warning("数据层指纹保存失败 (不影响主流程): %s", exc)

    return final_df


def _insert_or_ignore(table, conn, keys, data_iter):
    """pandas to_sql method: INSERT OR IGNORE, 跳过已有 PK 行"""
    cols = ", ".join(f'"{k}"' for k in keys)
    placeholders = ", ".join(["?"] * len(keys))
    sql = f'INSERT OR IGNORE INTO "{table.name}" ({cols}) VALUES ({placeholders})'
    # 显式事务包裹每个 chunk，避免 autocommit 模式下逐行提交
    conn.execute("BEGIN")
    try:
        conn.executemany(sql, data_iter)
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise


def _upsert_on_pk(table, conn, keys, data_iter):
    """pandas to_sql method: upsert by daily_bar primary key (date, code)."""
    cols = list(keys)
    quoted_cols = ", ".join(f'"{k}"' for k in cols)
    placeholders = ", ".join(["?"] * len(cols))
    update_cols = [c for c in cols if c not in {"date", "code"}]

    if update_cols:
        assignments = ", ".join(f'"{c}" = excluded."{c}"' for c in update_cols)
        conflict_clause = f"DO UPDATE SET {assignments}"
    else:
        conflict_clause = "DO NOTHING"

    sql = (
        f'INSERT INTO "{table.name}" ({quoted_cols}) VALUES ({placeholders}) '
        f'ON CONFLICT("date", "code") {conflict_clause}'
    )
    conn.execute("BEGIN")
    try:
        conn.executemany(sql, data_iter)
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise


def _upsert_daily_bar(con, df: pd.DataFrame) -> None:
    """
    统一的 daily_bar upsert 函数。

    使用 ON CONFLICT(date, code) DO UPDATE 实现：
    - 新主键行插入
    - 已存在主键行更新（修复历史 NULL 值）

    参数:
        con: sqlite3 原生连接（非 wrapper）
        df: DataFrame，必须包含 canonical 列（raw_ 前缀）
    """
    cols = [
        "date", "code", "raw_open", "raw_high", "raw_low", "raw_close",
        "raw_volume", "raw_amount", "raw_pctChg", "raw_turn",
        "raw_peTTM", "raw_pbMRQ", "raw_psTTM", "raw_pcfNcfTTM",
        "fwd_factor", "bwd_factor", "corp_action_flag", "factor_source", "factor_updated_at",
        "cum_factor", "isST", "tradestatus", "industry",
    ]

    work = df.copy()

    # 补齐缺失列，避免不同入口字段不一致
    for c in cols:
        if c not in work.columns:
            work[c] = None

    work = work[cols].copy()
    work["date"] = pd.to_datetime(work["date"]).dt.strftime("%Y-%m-%d %H:%M:%S")

    placeholders = ", ".join(["?"] * len(cols))
    quoted_cols = ", ".join([f'"{c}"' for c in cols])

    update_cols = [c for c in cols if c not in ["date", "code"]]
    update_clause = ", ".join([f'"{c}"=excluded."{c}"' for c in update_cols])

    sql = f'''
    INSERT INTO daily_bar ({quoted_cols})
    VALUES ({placeholders})
    ON CONFLICT(date, code) DO UPDATE SET
    {update_clause}
    '''

    rows = list(work.itertuples(index=False, name=None))
    con.execute("BEGIN")
    try:
        con.executemany(sql, rows)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise


def ingest_daily_bar_df(df: pd.DataFrame, cfg: dict) -> None:
    """
    公共入口：将 DataFrame 写入 daily_bar 表。

    API 和 ETL 统一调用此函数，确保：
    - 统一的 raw_ 前缀处理
    - 统一的 cum_factor 计算
    - 统一的 industry 映射
    - 统一的 upsert 语义

    参数:
        df: 原始格式 DataFrame（无 raw_ 前缀）
        cfg: 配置字典
    """
    # 应用 raw_ 前缀
    df = _apply_raw_prefix(df)

    # 关联行业映射
    df = _join_industry(df, cfg)

    # 计算 cum_factor
    df = _ensure_cum_factor(df)
    df = _ensure_price_factors(df, factor_source="ingest_daily_bar_df")

    # 获取原生 sqlite 连接
    from src.data_layer.db import get_connection
    con = get_connection(cfg)

    # 获取底层 sqlite3 连接（如果 con 是 wrapper）
    if hasattr(con, "_con"):
        raw_con = con._con
    else:
        raw_con = con

    # 执行 upsert
    raw_con.execute("PRAGMA busy_timeout=60000")
    try:
        _upsert_daily_bar(raw_con, df)
    finally:
        raw_con.execute("PRAGMA busy_timeout=5000")


def _detect_rebuild_codes(df: pd.DataFrame, cfg: dict) -> set[str]:
    """
    Detect codes requiring historical rebuild after factor updates.

    Triggers:
      1) recent rows in current batch carry corp_action_flag=1
      2) factor values differ from existing DB rows on same (date, code)
    """
    if df.empty:
        return set()

    from src.data_layer.db import get_connection

    con = get_connection(cfg)
    flag_series = pd.to_numeric(df.get("corp_action_flag", 0), errors="coerce").fillna(0).astype(int)
    date_series = (
        pd.to_datetime(df["date"], errors="coerce").dt.normalize()
        if "date" in df.columns
        else pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    )
    max_row = con.execute("SELECT MAX(DATE(date)) FROM daily_bar").fetchone()
    if max_row and max_row[0]:
        current_db_max = pd.to_datetime(max_row[0]).normalize()
        recent_start = current_db_max - pd.Timedelta(days=2)
        flag_mask = flag_series.eq(1) & date_series.ge(recent_start)
    else:
        flag_mask = flag_series.eq(1)
    flagged = set(df.loc[flag_mask, "code"].astype(str).tolist())

    codes = sorted(set(df["code"].astype(str).tolist()))
    if not codes:
        return flagged

    placeholders = ", ".join(["?"] * len(codes))
    try:
        existing = con.execute(
            f"""
            SELECT DATE(date) AS date, code, fwd_factor, bwd_factor
            FROM daily_bar
            WHERE code IN ({placeholders})
            """,
            codes,
        ).df()
    except Exception:
        return flagged
    if existing.empty:
        return flagged

    incoming = df[["date", "code", "fwd_factor", "bwd_factor"]].copy()
    incoming["date"] = pd.to_datetime(incoming["date"]).dt.strftime("%Y-%m-%d")
    incoming["code"] = incoming["code"].astype(str)
    existing["date"] = pd.to_datetime(existing["date"]).dt.strftime("%Y-%m-%d")
    existing["code"] = existing["code"].astype(str)

    merged = incoming.merge(
        existing,
        on=["date", "code"],
        how="inner",
        suffixes=("_new", "_old"),
    )
    if merged.empty:
        return flagged

    fwd_new = pd.to_numeric(merged["fwd_factor_new"], errors="coerce").fillna(1.0)
    fwd_old = pd.to_numeric(merged["fwd_factor_old"], errors="coerce").fillna(1.0)
    bwd_new = pd.to_numeric(merged["bwd_factor_new"], errors="coerce").fillna(1.0)
    bwd_old = pd.to_numeric(merged["bwd_factor_old"], errors="coerce").fillna(1.0)

    changed = (fwd_new.sub(fwd_old).abs() > 1e-10) | (bwd_new.sub(bwd_old).abs() > 1e-10)
    changed_codes = set(merged.loc[changed, "code"].astype(str).tolist())
    return flagged | changed_codes


def _ingest_to_db(df: pd.DataFrame, cfg: dict, update_mode: str = "full") -> None:
    """
    将 ETL 产出写入 SQLite daily_bar 表 + industry_map 表。

    canonical 层契约: 入库失败必须阻断主流程 (抛出异常)，
    不允许 warning 后继续下游研究流程。

    增量语义 (UPSERT):
      daily_bar 有 PRIMARY KEY (date, code)，增量入库时按主键更新已有行、
      插入新行。这样可以修复历史补录或上游字段曾经为 NULL 的行。
      日志仍用前/后行数差值计算实际新增，更新行不计入新增。
    """
    from src.data_layer.db import (
        enqueue_rebuild_codes,
        get_connection,
        record_version,
    )

    con = get_connection(cfg)
    df = _ensure_price_factors(df, factor_source="ingest_to_db")

    # 获取底层 sqlite3 连接（如果 con 是 wrapper）
    if hasattr(con, "_con"):
        raw_con = con._con
    else:
        raw_con = con

    daily_bar_cols = [
        "date", "code", "raw_open", "raw_high", "raw_low", "raw_close",
        "raw_volume", "raw_amount", "raw_pctChg", "raw_turn",
        "raw_peTTM", "raw_pbMRQ", "raw_psTTM", "raw_pcfNcfTTM",
        "fwd_factor", "bwd_factor", "corp_action_flag", "factor_source", "factor_updated_at",
        "cum_factor", "isST", "tradestatus", "industry",
    ]

    if update_mode == "incremental":
        rebuild_codes = _detect_rebuild_codes(df, cfg)
        before_row = con.execute(
            "SELECT COUNT(*), COUNT(DISTINCT code) FROM daily_bar"
        ).fetchone()
        before_count, before_codes = before_row

        # 使用统一的 upsert 函数
        raw_con.execute("PRAGMA busy_timeout=60000")
        try:
            _upsert_daily_bar(raw_con, df)
        finally:
            raw_con.execute("PRAGMA busy_timeout=5000")

        after_row = con.execute(
            "SELECT COUNT(*), COUNT(DISTINCT code) FROM daily_bar"
        ).fetchone()
        after_count, after_codes = after_row
        inserted = after_count - before_count
        new_codes = after_codes - before_codes

        if inserted == 0:
            print(f"[DB] daily_bar: 增量 upsert 完成，无新增主键 "
                  f"(DB: {before_count:,} 行, {before_codes} 代码)")
        else:
            parts = [f"共 {inserted:,} 行"]
            if new_codes > 0:
                parts.append(f"新代码 {new_codes} 只")
            print(f"[DB] daily_bar: 增量写入 {', '.join(parts)} "
                  f"(DB 总量: {after_count:,} 行, {after_codes} 代码)")
    else:
        # 全量覆盖
        con.execute("DELETE FROM daily_bar")
        # 使用统一的 upsert 函数（全量模式也走 upsert 逻辑）
        raw_con.execute("PRAGMA busy_timeout=60000")
        try:
            _upsert_daily_bar(raw_con, df)
        finally:
            raw_con.execute("PRAGMA busy_timeout=5000")
        print(f"[DB] daily_bar: 全量覆盖 {len(df):,} 行")

    if update_mode == "incremental" and rebuild_codes:
        queued = enqueue_rebuild_codes(
            cfg,
            sorted(rebuild_codes),
            reason="corp_action_or_factor_revision",
            trigger_date=pd.Timestamp.now().strftime("%Y-%m-%d"),
        )
        print(
            f"[REBUILD] factor change detected; queued {queued} codes "
            f"for historical rebuild"
        )

    record_version(
        cfg, "daily_bar",
        version=pd.Timestamp.now().strftime("%Y%m%d_%H%M%S"),
        row_count=len(df),
        col_count=len(daily_bar_cols),
    )

    # industry_map 维度表：有数据就跳过，无数据时从 Parquet 导入
    ind_count = con.execute("SELECT COUNT(*) FROM industry_map").fetchone()[0]
    if ind_count == 0:
        industry_path = cfg["etl"].get("industry_map")
        if industry_path and os.path.exists(industry_path):
            ind_df = pd.read_parquet(industry_path)
            if "code" in ind_df.columns and "industry" in ind_df.columns:
                ind_df = ind_df[["code", "industry"]].drop_duplicates("code")
                con.df_to_table("industry_map", ind_df)
                print(f"[DB] industry_map: 首次写入 {len(ind_df)} 行")
        else:
            print("[WARN] industry_map 为空且映射文件不存在，行业信息暂缺")
    else:
        print(f"[DB] SQLite industry_map: 已有 {ind_count} 行，跳过")


def _reconcile_raw_db(raw_df: pd.DataFrame, cfg: dict) -> dict:
    """
    入库后对账：比较 raw 汇总与 daily_bar 的覆盖范围。

    检查维度：
      - 行数、代码数、日期范围
      - 代码集合差异 (raw 独有 / DB 独有)
      - (date,code) 键差异采样

    不可解释差异时抛出 ValueError 阻断后续流程。
    """
    from src.data_layer.db import get_connection

    con = get_connection(cfg)

    db_row = con.execute(
        "SELECT COUNT(*) , COUNT(DISTINCT code), MIN(date), MAX(date) FROM daily_bar"
    ).fetchone()
    db_rows, db_n_codes, db_min_date, db_max_date = db_row

    raw_rows = len(raw_df)
    raw_codes = set(raw_df["code"].unique())
    raw_n_codes = len(raw_codes)
    raw_min_date = str(raw_df["date"].min().date())
    raw_max_date = str(raw_df["date"].max().date())

    print(f"\n{'='*55}")
    print(f"[RECONCILE] raw vs daily_bar 对账")
    print(f"  raw:      {raw_rows:>12,} 行 | {raw_n_codes:>6} 代码 | {raw_min_date} ~ {raw_max_date}")
    print(f"  daily_bar:{db_rows:>12,} 行 | {db_n_codes:>6} 代码 | {db_min_date} ~ {db_max_date}")

    report = {
        "raw_rows": raw_rows, "db_rows": db_rows,
        "raw_codes": raw_n_codes, "db_codes": db_n_codes,
        "raw_date_range": (raw_min_date, raw_max_date),
        "db_date_range": (db_min_date, db_max_date),
    }

    # ── 代码集合对比 ──
    db_codes = set(
        r[0] for r in con.execute("SELECT DISTINCT code FROM daily_bar").fetchall()
    )
    raw_only = raw_codes - db_codes
    db_only = db_codes - raw_codes
    report["raw_only_codes"] = len(raw_only)
    report["db_only_codes"] = len(db_only)

    if raw_only:
        samples = sorted(raw_only)[:20]
        print(f"  raw 独有代码: {len(raw_only)} 只 (前20: {', '.join(samples)})")
    if db_only:
        samples = sorted(db_only)[:20]
        print(f"  DB 独有代码:  {len(db_only)} 只 (前20: {', '.join(samples)})")

    # ── 判定 ──
    if not raw_only and not db_only:
        if raw_rows == db_rows:
            print(f"  [OK] raw 与 daily_bar 完全一致")
        else:
            diff = db_rows - raw_rows
            print(f"  [OK] 代码一致，DB 比 raw 多 {diff:+,} 行 "
                  f"(历史入库 / raw 重复键去重)")
    elif raw_only:
        # raw 有代码未入库 -> 阻断
        print(f"  [FAIL] raw 独有代码未入库: {len(raw_only)} 只")
        print(f"{'='*55}\n")
        raise ValueError(
            f"canonical 对账失败: raw 有 {len(raw_only)} 个代码未入库 "
            f"(raw {raw_n_codes} 代码, daily_bar {db_n_codes} 代码)。"
            f"请检查 INSERT OR IGNORE 是否正常执行。"
        )
    else:
        # db_only 但无 raw_only: DB 有历史数据，raw 本轮未覆盖 -> 正常
        diff = db_rows - raw_rows
        print(f"  [OK] raw 全量已入库; DB 另有 {len(db_only)} 只历史代码 "
              f"(DB 比 raw 多 {diff:+,} 行)")

    print(f"{'='*55}\n")
    return report
