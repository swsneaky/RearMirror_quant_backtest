"""
增量特征计算诊断脚本
====================
诊断问题：
1. 每一步的日期范围 + 行数
2. 4/8 到 4/15 期间哪些列开始大面积变 NaN
3. daily_bar 在尾部几天的原始字段缺失情况
"""
import sqlite3
import pandas as pd
import numpy as np
from src.config_loader import load_config

def run_diagnostics():
    cfg = load_config()
    db_path = cfg.get("database", {}).get("path", "data/quant.db")

    print("=" * 60)
    print("诊断报告：增量特征计算问题")
    print("=" * 60)

    # 1. 检查 daily_bar 表状态
    print("\n" + "=" * 60)
    print("【1】daily_bar 表状态")
    print("=" * 60)

    conn = sqlite3.connect(db_path)

    # 基本信息
    result = conn.execute("SELECT COUNT(*) FROM daily_bar").fetchone()
    total_rows = result[0]
    print(f"总行数: {total_rows:,}")

    result = conn.execute("SELECT MIN(DATE(date)), MAX(DATE(date)) FROM daily_bar").fetchone()
    print(f"日期范围: {result[0]} ~ {result[1]}")

    # 每天的行数（最近20天）
    print("\n最近 20 个交易日每天行数:")
    daily_counts = pd.read_sql_query("""
        SELECT DATE(date) as d, COUNT(*) as cnt
        FROM daily_bar
        GROUP BY DATE(date)
        ORDER BY d DESC
        LIMIT 20
    """, conn)
    print(daily_counts.to_string(index=False))

    # 2. 检查 cum_factor 缺失情况
    print("\n" + "=" * 60)
    print("【2】cum_factor 缺失情况（按日期）")
    print("=" * 60)

    cum_factor_stats = pd.read_sql_query("""
        SELECT DATE(date) as d,
               COUNT(*) as total,
               COUNT(cum_factor) as non_null,
               ROUND(COUNT(cum_factor) * 100.0 / COUNT(*), 2) as pct_non_null
        FROM daily_bar
        GROUP BY DATE(date)
        ORDER BY d DESC
        LIMIT 20
    """, conn)
    print(cum_factor_stats.to_string(index=False))

    # 3. 检查原始字段缺失情况（4/8 ~ 4/15）
    print("\n" + "=" * 60)
    print("【3】原始字段缺失情况 (4/8 ~ 4/15)")
    print("=" * 60)

    # 先看表结构
    schema = pd.read_sql_query("PRAGMA table_info(daily_bar)", conn)
    print("daily_bar 表字段:")
    print(schema['name'].tolist())

    # 检查关键字段
    key_cols = ["open", "high", "low", "close", "vol", "amount",
                "turnover_rate", "pe", "pb", "ps", "dv_ratio",
                "cum_factor", "raw_turn", "raw_peTTM", "raw_pbMRQ",
                "raw_psTTM", "raw_pcfNcfTTM"]

    # 获取实际存在的列
    actual_cols = schema['name'].tolist()
    check_cols = [c for c in key_cols if c in actual_cols]

    if check_cols:
        cols_sql = ", ".join([f"COUNT({c}) as cnt_{c}" for c in check_cols])
        raw_missing = pd.read_sql_query(f"""
            SELECT DATE(date) as d, COUNT(*) as total, {cols_sql}
            FROM daily_bar
            WHERE DATE(date) >= '2026-04-01'
            GROUP BY DATE(date)
            ORDER BY d
        """, conn)

        print("\n原始字段非空计数:")
        print(raw_missing.to_string(index=False))

        # 计算缺失率
        print("\n原始字段缺失率 (%):")
        for col in check_cols:
            if f"cnt_{col}" in raw_missing.columns:
                raw_missing[f"pct_missing_{col}"] = (
                    (raw_missing["total"] - raw_missing[f"cnt_{col}"]) * 100.0 / raw_missing["total"]
                ).round(2)

        # 只显示缺失率相关的列
        pct_cols = ["d"] + [c for c in raw_missing.columns if c.startswith("pct_missing_")]
        print(raw_missing[pct_cols].to_string(index=False))

    # 4. 增量计算流程诊断
    print("\n" + "=" * 60)
    print("【4】增量计算流程诊断")
    print("=" * 60)

    # 模拟增量计算的切片逻辑
    feat_cfg = cfg["features"]
    windows = feat_cfg["windows"]
    max_window = max(windows)
    safety_margin = 10
    warmup_days = max_window + safety_margin

    # 假设旧矩阵最新日期
    old_max_str = "2026-03-31"

    # 获取新交易日
    new_dates_df = pd.read_sql_query(
        f"SELECT DISTINCT DATE(date) as date FROM daily_bar WHERE DATE(date) > DATE('{old_max_str}') ORDER BY date",
        conn
    )
    n_new_dates = len(new_dates_df)
    print(f"新交易日数量: {n_new_dates}")
    print(f"新交易日: {new_dates_df['date'].tolist()}")

    # 获取预热期间的交易日
    dates_df = pd.read_sql_query(
        f"SELECT DISTINCT date FROM daily_bar ORDER BY date DESC LIMIT {warmup_days + n_new_dates}",
        conn
    )
    dates_df['date'] = pd.to_datetime(dates_df['date'], format='mixed').dt.normalize()
    dates_df = dates_df.sort_values('date')
    warmup_start = dates_df['date'].iloc[0]

    print(f"预热起点 (warmup_start): {warmup_start.date()}")
    print(f"max_window: {max_window}, safety_margin: {safety_margin}")

    # 加载切片数据
    slice_df = pd.read_sql_query(
        f"SELECT * FROM daily_bar WHERE date >= '{warmup_start.date()}' ORDER BY code, date",
        conn
    )

    print(f"\n【检查点 1】slice_df:")
    slice_df['date'] = pd.to_datetime(slice_df['date'], format='mixed')
    print(f"  日期范围: {slice_df['date'].min().date()} ~ {slice_df['date'].max().date()}")
    print(f"  行数: {len(slice_df):,}")
    print(f"  每天行数:")
    daily_slice = slice_df.groupby(slice_df['date'].dt.date).size()
    print(daily_slice.tail(20).to_string())

    # 5. 模拟复权价计算
    print("\n" + "=" * 60)
    print("【5】复权价计算诊断")
    print("=" * 60)

    # 检查 cum_factor 对 _close_adj 的影响
    slice_df["_close_adj"] = slice_df["raw_close"] * slice_df["cum_factor"]

    print("cum_factor 和 _close_adj 缺失情况:")
    adj_stats = slice_df.groupby(slice_df['date'].dt.date).agg({
        'code': 'count',
        'cum_factor': lambda x: x.isna().sum(),
        '_close_adj': lambda x: x.isna().sum()
    }).rename(columns={'code': 'total', 'cum_factor': 'cum_factor_nan', '_close_adj': '_close_adj_nan'})

    # 只显示最近 20 天
    print(adj_stats.tail(20).to_string())

    # 6. 检查原始特征矩阵状态
    print("\n" + "=" * 60)
    print("【6】原始特征矩阵状态")
    print("=" * 60)

    raw_output = feat_cfg.get("raw_feature_output", "data/features/zz500_alpha158_raw.parquet")
    import os
    if os.path.exists(raw_output):
        import pyarrow.parquet as pq
        date_table = pq.read_table(raw_output, columns=['date'])
        existing_dates = date_table['date'].to_pandas()
        existing_dates = pd.to_datetime(existing_dates)
        print(f"原始矩阵路径: {raw_output}")
        print(f"总行数: {len(existing_dates):,}")
        print(f"日期范围: {existing_dates.min().date()} ~ {existing_dates.max().date()}")

        # 每天行数
        print("\n最近 20 天每天行数:")
        daily_feat = existing_dates.groupby(existing_dates.dt.date).size()
        print(daily_feat.tail(20).to_string())
    else:
        print(f"原始矩阵不存在: {raw_output}")

    # 7. 详细 NaN 分析（按列）
    print("\n" + "=" * 60)
    print("【7】4/8 ~ 4/15 期间各列 NaN 分析")
    print("=" * 60)

    # 只分析最近的数据
    tail = slice_df[slice_df["date"] >= "2026-04-08"].copy()

    if len(tail) > 0:
        # 检查原始列
        raw_cols = [c for c in slice_df.columns if c.startswith("raw_") or c in ["open", "high", "low", "close", "vol", "amount", "cum_factor"]]
        print("\n原始列缺失率 (%):")

        nan_by_day = {}
        for d, sub in tail.groupby(tail["date"].dt.date):
            nan_pct = (sub[raw_cols].isna().mean() * 100).round(2)
            nan_by_day[str(d)] = nan_pct[nan_pct > 0].sort_values(ascending=False)

        for d, s in nan_by_day.items():
            if len(s) > 0:
                print(f"\n==== {d} ====")
                print(s.head(20).to_string())
            else:
                print(f"\n==== {d} ====")
                print("无缺失")

    conn.close()

    print("\n" + "=" * 60)
    print("诊断完成")
    print("=" * 60)


if __name__ == "__main__":
    run_diagnostics()
