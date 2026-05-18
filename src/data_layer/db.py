"""
SQLite 统一数据库 -- 连接管理 + Schema 初始化

从 DuckDB 迁移到 SQLite (WAL 模式) 以解决多进程并发访问问题。
SQLite WAL 允许多进程同时读 + 单进程写，互不阻塞。

职责：
  - 提供全局唯一的 SQLite 连接（单例模式, WAL + busy_timeout）
  - 初始化固定 Schema 表 (daily_bar, industry_map, index_bar, ...)
  - 动态表 (feature_wide, label_wide) 由对应 Store 按 DataFrame 结构创建
  - 实验表 (predictions, holdings, nav_daily, metrics_summary) 支持多实验 append
  - data_versions 元数据跟踪

设计原则：
  - SQLite 是唯一分析数据库，Parquet 作为 fallback / import-export 格式
  - WAL 模式：Dashboard (读) 与 Task Worker (写) 可并发
  - 宽表设计 (非 EAV)，因子/标签列直接作为 SQL 列
  - 所有表以 (date, code) 为逻辑复合主键
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager

import pandas as pd
import logging as _logging

_db_logger = _logging.getLogger(__name__)


# ─── SQLite ↔ DuckDB 兼容层 ─────────────────────────────
# 提供 .df() / .description 等 DuckDB 常用 API，让调用方无需改动

class _Result:
    """Wraps sqlite3.Cursor result to provide DuckDB-compatible .df() method."""

    def __init__(self, cursor: sqlite3.Cursor):
        self._cursor = cursor
        self.description = cursor.description

    def df(self) -> pd.DataFrame:
        rows = self._cursor.fetchall()
        if not rows or not self.description:
            return pd.DataFrame()
        cols = [d[0] for d in self.description]
        return pd.DataFrame(rows, columns=cols)

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()


class _CursorWrapper:
    """Wraps sqlite3.Cursor for the cursor() context manager (DuckDB-compatible)."""

    def __init__(self, raw_cursor: sqlite3.Cursor):
        self._cursor = raw_cursor
        self.description = None

    def execute(self, sql: str, params=None):
        self._cursor.execute(sql, params or [])
        self.description = self._cursor.description
        return self  # DuckDB cursors return self for chaining

    def df(self) -> pd.DataFrame:
        rows = self._cursor.fetchall()
        if not rows or not self.description:
            return pd.DataFrame()
        cols = [d[0] for d in self.description]
        return pd.DataFrame(rows, columns=cols)

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def close(self):
        self._cursor.close()


class _Connection:
    """Wraps sqlite3.Connection to provide DuckDB-compatible API."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self.description = None

    # ── DuckDB-compatible execute ────────────────────────

    def execute(self, sql: str, params=None) -> _Result:
        cursor = self._conn.execute(sql, params or [])
        result = _Result(cursor)
        self.description = result.description
        return result

    def executemany(self, sql: str, params_seq) -> _Result:
        cursor = self._conn.executemany(sql, params_seq)
        return _Result(cursor)

    # ── DataFrame ↔ Table (替代 DuckDB 的 SELECT * FROM <df>) ──

    def df_to_table(
        self,
        table_name: str,
        df: pd.DataFrame,
        if_exists: str = "append",
        chunksize: int | None = None,
        method: str | None = None,
    ) -> None:
        """
        Write DataFrame to SQLite table.
        Replaces DuckDB's ``SELECT * FROM <python_df>`` pattern.

        Parameters
        ----------
        chunksize : 每批写入行数 (None = 一次性全部写入)
        method : pandas to_sql method, 推荐 "multi" 加速批量插入

        Uses DEFERRED isolation during write to batch INSERTs into a
        single transaction (avoids per-row fsync under autocommit).
        """
        old_isolation = self._conn.isolation_level
        self._conn.isolation_level = "DEFERRED"
        try:
            df.to_sql(
                table_name, self._conn,
                if_exists=if_exists, index=False,
                chunksize=chunksize, method=method,
            )
        finally:
            self._conn.isolation_level = old_isolation

    # ── Other standard methods ───────────────────────────

    def cursor(self) -> _CursorWrapper:
        return _CursorWrapper(self._conn.cursor())

    def close(self):
        self._conn.close()

    def commit(self):
        self._conn.commit()


# ─── 全局单例 ────────────────────────────────────────────
_lock = threading.Lock()
_connections: dict[str, _Connection] = {}


def set_read_only_mode(enabled: bool = True) -> None:
    """SQLite WAL 模式天然支持并发读写 -- 保留为空操作以兼容旧代码。"""
    pass


def get_db_path(cfg: dict) -> str:
    """从配置读取数据库路径"""
    return cfg.get("database", {}).get("path", "data/quant.db")


def get_connection(cfg: dict, **_kw) -> _Connection:
    """
    获取全局 SQLite 连接（单例, WAL 模式）。

    WAL 模式支持并发: 多进程可同时读，单进程写不阻塞其他读。
    busy_timeout=5000ms 避免短暂写冲突导致 "database is locked"。

    兼容旧版 DuckDB 签名 (``read_only`` 关键字被忽略)。
    """
    db_path = get_db_path(cfg)
    abs_path = os.path.abspath(db_path)
    with _lock:
        if abs_path not in _connections:
            os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
            raw = sqlite3.connect(
                abs_path,
                check_same_thread=False,
                isolation_level=None,   # autocommit (matches DuckDB behavior)
            )
            raw.execute("PRAGMA journal_mode=WAL")
            raw.execute("PRAGMA busy_timeout=5000")
            con = _Connection(raw)
            _init_schema(con)
            _connections[abs_path] = con
        return _connections[abs_path]


def close_connection(cfg: dict) -> None:
    """显式关闭指定数据库的连接（测试 / 清理用）"""
    db_path = get_db_path(cfg)
    abs_path = os.path.abspath(db_path)
    with _lock:
        con = _connections.pop(abs_path, None)
        if con:
            con.close()


@contextmanager
def cursor(cfg: dict):
    """
    上下文管理器：获取 cursor，结束时自动关闭。

    用法::

        with cursor(cfg) as cur:
            cur.execute("SELECT * FROM daily_bar LIMIT 10")
            df = cur.df()
    """
    con = get_connection(cfg)
    cur = con.cursor()
    try:
        yield cur
    finally:
        cur.close()


# ─── Schema 初始化 ───────────────────────────────────────

def _init_schema(con: _Connection) -> None:
    """
    创建固定 Schema 表 (IF NOT EXISTS)。
    动态表 (feature_wide, label_wide) 不在此创建 -- 由 Store 写入时按 DataFrame 结构生成。
    """
    con.execute("""
        CREATE TABLE IF NOT EXISTS daily_bar (
            date         TEXT    NOT NULL,
            code         TEXT    NOT NULL,
            raw_open     REAL,
            raw_high     REAL,
            raw_low      REAL,
            raw_close    REAL,
            raw_volume   REAL,
            raw_amount   REAL,
            raw_pctChg   REAL,
            raw_turn     REAL,
            raw_peTTM    REAL,
            raw_pbMRQ    REAL,
            raw_psTTM    REAL,
            raw_pcfNcfTTM REAL,
            fwd_factor   REAL,
            bwd_factor   REAL,
            corp_action_flag INTEGER DEFAULT 0,
            factor_source TEXT,
            factor_updated_at TEXT,
            cum_factor   REAL,
            isST         INTEGER DEFAULT 0,
            tradestatus  INTEGER DEFAULT 1,
            industry     TEXT,
            PRIMARY KEY (date, code)
        )
    """)

    # 迁移：为已有 daily_bar 表补充列
    try:
        con.execute("ALTER TABLE daily_bar ADD COLUMN industry TEXT")
    except sqlite3.OperationalError:
        pass  # 列已存在
    try:
        con.execute("ALTER TABLE daily_bar ADD COLUMN fwd_factor REAL")
    except sqlite3.OperationalError:
        pass
    try:
        con.execute("ALTER TABLE daily_bar ADD COLUMN bwd_factor REAL")
    except sqlite3.OperationalError:
        pass
    try:
        con.execute("ALTER TABLE daily_bar ADD COLUMN corp_action_flag INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        con.execute("ALTER TABLE daily_bar ADD COLUMN factor_source TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        con.execute("ALTER TABLE daily_bar ADD COLUMN factor_updated_at TEXT")
    except sqlite3.OperationalError:
        pass

    con.execute("""
        CREATE TABLE IF NOT EXISTS industry_map (
            code     TEXT PRIMARY KEY,
            industry TEXT
        )
    """)

    # 股票元信息表 -- 名称、上市日期等
    con.execute("""
        CREATE TABLE IF NOT EXISTS stock_info (
            code         TEXT PRIMARY KEY,
            name         TEXT,
            industry     TEXT,
            list_date    TEXT,
            delist_date  TEXT,
            market       TEXT,
            updated_at   TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 股票最新数据缓存 -- 避免每次翻页都全表聚合
    con.execute("""
        CREATE TABLE IF NOT EXISTS stock_latest (
            code          TEXT PRIMARY KEY,
            latest_date   TEXT,
            raw_close     REAL,
            raw_pctChg    REAL,
            raw_volume    REAL,
            raw_amount    REAL,
            raw_turn      REAL,
            raw_peTTM     REAL,
            raw_pbMRQ     REAL,
            isST          INTEGER DEFAULT 0,
            bar_count     INTEGER DEFAULT 0,
            updated_at    TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 为 stock_latest 创建索引
    con.execute("CREATE INDEX IF NOT EXISTS idx_stock_latest_close ON stock_latest(raw_close)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_stock_latest_pctchg ON stock_latest(raw_pctChg)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_stock_latest_turn ON stock_latest(raw_turn)")

    con.execute("""
        CREATE TABLE IF NOT EXISTS index_bar (
            date    TEXT    NOT NULL,
            code    TEXT    NOT NULL,
            close   REAL,
            pctChg  REAL,
            PRIMARY KEY (date, code)
        )
    """)

    # 实验结果表 -- 支持多实验 append
    con.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            experiment_id TEXT NOT NULL,
            date          TEXT NOT NULL,
            code          TEXT NOT NULL,
            pred_score    REAL,
            pred_rank     REAL,
            selected      INTEGER,
            label_value   REAL,
            raw_pctChg    REAL,
            cost_ratio    REAL,
            turnover_ratio REAL,
            PRIMARY KEY (experiment_id, date, code)
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS holdings (
            experiment_id TEXT NOT NULL,
            date          TEXT NOT NULL,
            code          TEXT NOT NULL,
            weight        REAL,
            is_new        INTEGER,
            is_exit       INTEGER,
            PRIMARY KEY (experiment_id, date, code)
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS nav_daily (
            experiment_id TEXT    NOT NULL,
            date          TEXT    NOT NULL,
            nav           REAL,
            bench_nav     REAL,
            excess_nav    REAL,
            cost_ratio    REAL,
            turnover_ratio REAL,
            PRIMARY KEY (experiment_id, date)
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS metrics_summary (
            experiment_id       TEXT PRIMARY KEY,
            ann_return          REAL,
            ann_excess_return   REAL,
            ann_volatility      REAL,
            tracking_error      REAL,
            sharpe_ratio        REAL,
            information_ratio   REAL,
            max_drawdown        REAL,
            excess_max_drawdown REAL,
            avg_turnover        REAL,
            avg_cost_per_period REAL,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # 元数据版本跟踪 (legacy, 保留兼容)
    con.execute("""
        CREATE TABLE IF NOT EXISTS data_versions (
            asset_name   TEXT NOT NULL,
            version      TEXT NOT NULL,
            config_hash  TEXT,
            row_count    INTEGER,
            col_count    INTEGER,
            created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
            extra        TEXT,
            PRIMARY KEY (asset_name, version)
        )
    """)

    # ============================================================
    # v2 元数据基础设施 -- 版本化数据资产
    # ============================================================

    con.execute("""
        CREATE TABLE IF NOT EXISTS asset_registry (
            asset_id     TEXT PRIMARY KEY,
            asset_type   TEXT NOT NULL,
            name         TEXT NOT NULL,
            version      TEXT NOT NULL,
            config_hash  TEXT NOT NULL,
            parent_ids   TEXT,
            status       TEXT DEFAULT 'active',
            table_name   TEXT,
            row_count    INTEGER,
            col_count    INTEGER,
            created_at   TEXT DEFAULT CURRENT_TIMESTAMP,
            meta_json    TEXT,
            UNIQUE(asset_type, config_hash)
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS factor_definitions (
            factor_id     TEXT PRIMARY KEY,
            factor_group  TEXT NOT NULL,
            code_hash     TEXT NOT NULL,
            input_cols    TEXT NOT NULL,
            output_cols   TEXT NOT NULL,
            windows       TEXT,
            description   TEXT,
            created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(factor_group, code_hash)
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS feature_set_factors (
            feature_set_id TEXT NOT NULL,
            factor_id      TEXT NOT NULL,
            PRIMARY KEY (feature_set_id, factor_id)
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS factor_rebuild_queue (
            code          TEXT PRIMARY KEY,
            reason        TEXT,
            trigger_date  TEXT,
            status        TEXT DEFAULT 'pending',
            detected_at   TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ============================================================
    # v2 Phase E -- 实验血缘 + IC 分析结果表
    # ============================================================

    con.execute("""
        CREATE TABLE IF NOT EXISTS experiment_run (
            experiment_id        TEXT PRIMARY KEY,
            feature_set_id       TEXT,
            label_set_id         TEXT,
            model_name           TEXT,
            model_params_hash    TEXT,
            config_snapshot      TEXT,
            status               TEXT DEFAULT 'running',
            created_at           TEXT DEFAULT CURRENT_TIMESTAMP,
            finished_at          TEXT,
            meta_json            TEXT
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS factor_analysis_summary (
            analysis_id     TEXT NOT NULL,
            factor_name     TEXT NOT NULL,
            ic_mean         REAL,
            ic_std          REAL,
            icir            REAL,
            pos_ratio       REAL,
            feature_set_id  TEXT,
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (analysis_id, factor_name)
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS factor_ic_series (
            analysis_id     TEXT NOT NULL,
            date            TEXT NOT NULL,
            factor_name     TEXT NOT NULL,
            ic_value        REAL,
            PRIMARY KEY (analysis_id, date, factor_name)
        )
    """)


# ─── 工具函数 ────────────────────────────────────────────

def table_exists(cfg: dict, table_name: str) -> bool:
    """检查表是否存在"""
    con = get_connection(cfg)
    result = con.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name = ?",
        [table_name],
    ).fetchone()
    return result[0] > 0


def table_row_count(cfg: dict, table_name: str) -> int:
    """返回表行数，表不存在返回 0"""
    if not table_exists(cfg, table_name):
        return 0
    con = get_connection(cfg)
    return con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]


def list_table_columns(cfg: dict, table_name: str) -> list[str]:
    """返回表的所有列名 (替代 DuckDB information_schema.columns)"""
    con = get_connection(cfg)
    rows = con.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    return [r[1] for r in rows]


def ingest_dataframe(
    cfg: dict,
    table_name: str,
    df,
    mode: str = "replace",
) -> int:
    """
    将 DataFrame 写入 SQLite 表。

    Parameters
    ----------
    table_name : 目标表名
    df : pandas DataFrame
    mode :
        "replace"  -- DROP + CREATE (全量覆盖)
        "append"   -- INSERT INTO (追加)
        "upsert"   -- DELETE matching keys + INSERT (按 date+code 更新)

    Returns
    -------
    写入行数
    """
    con = get_connection(cfg)
    if mode == "replace":
        con.execute(f"DROP TABLE IF EXISTS {table_name}")
        con.df_to_table(table_name, df, chunksize=50_000)
    elif mode == "append":
        if_exists = "append" if table_exists(cfg, table_name) else "replace"
        con.df_to_table(table_name, df, if_exists=if_exists, chunksize=50_000)
    elif mode == "upsert":
        if not table_exists(cfg, table_name):
            con.df_to_table(table_name, df)
        else:
            # 用临时表做 upsert: 先删除重叠 key，再 append
            tmp = f"_tmp_{table_name}"
            con.df_to_table(tmp, df, if_exists="replace")
            con.execute(f"""
                DELETE FROM {table_name}
                WHERE (date, code) IN (SELECT date, code FROM {tmp})
            """)
            con.execute(f"INSERT INTO {table_name} SELECT * FROM {tmp}")
            con.execute(f"DROP TABLE IF EXISTS {tmp}")
    else:
        raise ValueError(f"不支持的 mode: {mode}")
    return len(df)


def record_version(
    cfg: dict,
    asset_name: str,
    version: str,
    row_count: int = 0,
    col_count: int = 0,
    config_hash: str = "",
    extra: str = "",
) -> None:
    """记录数据资产版本信息 (legacy, 保留兼容)"""
    con = get_connection(cfg)
    con.execute("""
        INSERT OR REPLACE INTO data_versions
            (asset_name, version, config_hash, row_count, col_count, extra)
        VALUES (?, ?, ?, ?, ?, ?)
    """, [asset_name, version, config_hash, row_count, col_count, extra])


# ============================================================
# v2 资产注册 API
# ============================================================

def register_asset(
    cfg: dict,
    asset_id: str,
    asset_type: str,
    name: str,
    config_hash: str,
    parent_ids: list[str] | None = None,
    table_name: str | None = None,
    row_count: int = 0,
    col_count: int = 0,
    meta: dict | None = None,
) -> None:
    """
    在 asset_registry 中注册一个版本化数据资产。

    如果 asset_id 已存在则更新 (幂等)。
    """
    import json

    con = get_connection(cfg)
    version = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    parent_json = json.dumps(parent_ids) if parent_ids else None
    meta_json = json.dumps(meta, default=str) if meta else None

    con.execute("DELETE FROM asset_registry WHERE asset_id = ?", [asset_id])
    con.execute("""
        INSERT INTO asset_registry
            (asset_id, asset_type, name, version, config_hash,
             parent_ids, status, table_name, row_count, col_count, meta_json)
        VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
    """, [asset_id, asset_type, name, version, config_hash,
          parent_json, table_name, row_count, col_count, meta_json])


def get_asset(cfg: dict, asset_id: str) -> dict | None:
    """查询单个资产的注册信息, 不存在返回 None"""
    con = get_connection(cfg)
    row = con.execute(
        "SELECT * FROM asset_registry WHERE asset_id = ?", [asset_id]
    ).fetchone()
    if row is None:
        return None
    cols = [d[0] for d in con.description]
    return dict(zip(cols, row))


def list_assets(cfg: dict, asset_type: str | None = None) -> list[dict]:
    """列出资产目录, 可按类型过滤"""
    con = get_connection(cfg)
    if asset_type:
        rows = con.execute(
            "SELECT * FROM asset_registry WHERE asset_type = ? ORDER BY created_at DESC",
            [asset_type],
        ).fetchall()
    else:
        rows = con.execute(
            "SELECT * FROM asset_registry ORDER BY created_at DESC"
        ).fetchall()
    cols = [d[0] for d in con.description]
    return [dict(zip(cols, r)) for r in rows]


def register_factor_def(
    cfg: dict,
    factor_id: str,
    factor_group: str,
    code_hash: str,
    input_cols: list[str],
    output_cols: list[str],
    windows: list[int] | None = None,
    description: str = "",
) -> None:
    """注册因子定义到 factor_definitions 表 (幂等)"""
    import json
    con = get_connection(cfg)
    con.execute("DELETE FROM factor_definitions WHERE factor_id = ?", [factor_id])
    con.execute("""
        INSERT INTO factor_definitions
            (factor_id, factor_group, code_hash, input_cols, output_cols, windows, description)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, [
        factor_id, factor_group, code_hash,
        json.dumps(input_cols), json.dumps(output_cols),
        json.dumps(windows) if windows else None,
        description,
    ])


def register_feature_set_factors(
    cfg: dict,
    feature_set_id: str,
    factor_ids: list[str],
) -> None:
    """登记某个 feature_set 由哪些 factor 组成"""
    con = get_connection(cfg)
    con.execute(
        "DELETE FROM feature_set_factors WHERE feature_set_id = ?",
        [feature_set_id],
    )
    for fid in factor_ids:
        con.execute(
            "INSERT INTO feature_set_factors (feature_set_id, factor_id) VALUES (?, ?)",
            [feature_set_id, fid],
        )


def enqueue_rebuild_codes(
    cfg: dict,
    codes: list[str],
    *,
    reason: str,
    trigger_date: str | None = None,
) -> int:
    """Add/refresh pending per-code rebuild tasks."""
    if not codes:
        return 0
    con = get_connection(cfg)
    inserted = 0
    for code in sorted(set(str(c) for c in codes)):
        con.execute(
            """
            INSERT INTO factor_rebuild_queue (code, reason, trigger_date, status, detected_at)
            VALUES (?, ?, ?, 'pending', CURRENT_TIMESTAMP)
            ON CONFLICT(code) DO UPDATE SET
                reason = excluded.reason,
                trigger_date = excluded.trigger_date,
                status = 'pending',
                detected_at = CURRENT_TIMESTAMP
            """,
            [code, reason, trigger_date],
        )
        inserted += 1
    return inserted


def get_pending_rebuild_codes(cfg: dict, limit: int | None = None) -> list[str]:
    """Fetch codes pending historical rebuild."""
    con = get_connection(cfg)
    sql = "SELECT code FROM factor_rebuild_queue WHERE status = 'pending' ORDER BY detected_at, code"
    params: list[object] = []
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))
    rows = con.execute(sql, params).fetchall()
    return [str(r[0]) for r in rows]


def mark_rebuild_codes_done(cfg: dict, codes: list[str]) -> int:
    """Mark queued rebuild tasks as done (idempotent)."""
    if not codes:
        return 0
    con = get_connection(cfg)
    done = 0
    for code in sorted(set(str(c) for c in codes)):
        con.execute(
            "UPDATE factor_rebuild_queue SET status = 'done' WHERE code = ?",
            [code],
        )
        done += 1
    return done


# ============================================================
# v2 Phase E: 实验血缘 API
# ============================================================

def register_experiment_run(
    cfg: dict,
    experiment_id: str,
    feature_set_id: str | None = None,
    label_set_id: str | None = None,
    model_name: str | None = None,
    model_params_hash: str | None = None,
    config_snapshot: str | None = None,
    meta: dict | None = None,
) -> None:
    """注册一次实验运行 (幂等)"""
    import json
    con = get_connection(cfg)
    meta_json = json.dumps(meta, default=str) if meta else None
    con.execute("DELETE FROM experiment_run WHERE experiment_id = ?", [experiment_id])
    con.execute("""
        INSERT INTO experiment_run
            (experiment_id, feature_set_id, label_set_id,
             model_name, model_params_hash, config_snapshot, status, meta_json)
        VALUES (?, ?, ?, ?, ?, ?, 'running', ?)
    """, [experiment_id, feature_set_id, label_set_id,
          model_name, model_params_hash, config_snapshot, meta_json])


def finish_experiment_run(cfg: dict, experiment_id: str, status: str = "done") -> None:
    """标记实验运行完成"""
    con = get_connection(cfg)
    con.execute("""
        UPDATE experiment_run SET status = ?, finished_at = CURRENT_TIMESTAMP
        WHERE experiment_id = ?
    """, [status, experiment_id])


def save_ic_analysis_results(
    cfg: dict,
    analysis_id: str,
    ic_df,
    summary,
    feature_set_id: str | None = None,
) -> None:
    """
    将 IC 分析结果写入数据库。

    Parameters
    ----------
    analysis_id : 本次分析的唯一 ID
    ic_df : IC 时间序列 (index=date, columns=factors)
    summary : ICIR 汇总 (index=factor, columns=[ic_mean, ic_std, icir, pos_ratio])
    feature_set_id : 关联的 feature_set 资产 ID
    """
    con = get_connection(cfg)

    # 写入 factor_analysis_summary
    con.execute("DELETE FROM factor_analysis_summary WHERE analysis_id = ?", [analysis_id])
    for factor_name, row in summary.iterrows():
        con.execute("""
            INSERT INTO factor_analysis_summary
                (analysis_id, factor_name, ic_mean, ic_std, icir, pos_ratio, feature_set_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, [analysis_id, str(factor_name),
              float(row.get("ic_mean", 0)), float(row.get("ic_std", 0)),
              float(row.get("icir", 0)), float(row.get("pos_ratio", 0)),
              feature_set_id])

    # 写入 factor_ic_series (长表)
    con.execute("DELETE FROM factor_ic_series WHERE analysis_id = ?", [analysis_id])
    if not ic_df.empty:
        tmp = ic_df.copy()
        tmp.index.name = "date"
        long = tmp.reset_index().melt(
            id_vars=["date"], var_name="factor_name", value_name="ic_value",
        )
        long["analysis_id"] = analysis_id
        long = long[["analysis_id", "date", "factor_name", "ic_value"]].dropna(subset=["ic_value"])
        con.df_to_table("factor_ic_series", long)
