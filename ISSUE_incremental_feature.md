# 增量特征计算问题调查报告

## 1. 问题现象

| 数据源 | 最新日期 | cum_factor 状态 |
|--------|----------|-----------------|
| SQLite daily_bar | 2026-04-15 | 04-09 后全部 NULL |
| parquet 缓存 | 2026-04-08 | 正常 |

---

## 2. 根本原因：两个写入入口，API 接口漏掉 cum_factor

搜索所有写入 daily_bar 的入口：

```
grep -R "df_to_table.*daily_bar|to_sql.*daily_bar|INSERT.*daily_bar" -n src/
```

结果：

| 文件 | 行号 | cum_factor |
|------|------|------------|
| `src/data_hub/etl_process.py` | 245 | ✅ 有 |
| **`api/routes/stocks.py`** | **697** | **❌ 无** |

---

## 3. 问题代码：API 接口 INSERT 语句漏掉 cum_factor

**文件**：`api/routes/stocks.py:697-717`

```python
# API 接口增量更新
def _run_incremental_update(cfg: dict):
    # ...
    for i, (code, start) in enumerate(need_update):
        rs = bs.query_history_k_data_plus(code, fields, ...)

        if data_rows:
            for row in data_rows:
                con.execute("""
                    INSERT OR IGNORE INTO daily_bar
                    (date, code, raw_open, raw_high, raw_low, raw_close, raw_volume, raw_amount,
                     raw_pctChg, isST, tradestatus, raw_turn, raw_peTTM, raw_pbMRQ, raw_psTTM, raw_pcfNcfTTM)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [...])
```

**只插入 16 列，缺少**：
- `cum_factor`
- `industry`

---

## 4. 正确代码：ETL 流程有 cum_factor

**文件**：`src/data_hub/etl_process.py:197-245`

```python
# ETL 合并入库
def _ingest_to_db(df: pd.DataFrame, cfg: dict, update_mode: str):
    daily_bar_cols = [
        "date", "code", "raw_open", "raw_high", "raw_low", "raw_close",
        "raw_volume", "raw_amount", "raw_pctChg", "raw_turn",
        "raw_peTTM", "raw_pbMRQ", "raw_psTTM", "raw_pcfNcfTTM",
        "cum_factor", "isST", "tradestatus", "industry",  # ← 有 cum_factor
    ]
    available = [c for c in daily_bar_cols if c in df.columns]
    ingest_df = df[available].copy()
    con.df_to_table("daily_bar", ingest_df, ...)
```

---

## 5. 时间线还原

1. 历史数据通过 `etl_process.py` 写入，**有 cum_factor**
2. 2026-04-09 之后的数据通过 **API 接口 `/update`** 写入
3. API 接口 INSERT 语句没有 `cum_factor` 列 → 数据库该列为 NULL
4. `build_alpha158()` 中 `_close_adj = raw_close * cum_factor` → NaN
5. `dropna(subset=['feat_ROC60'])` 删除所有 NaN 行

---

## 6. 修复方向

二选一：

1. **修复 API 接口**：在 INSERT 语句中添加 cum_factor 计算和插入
2. **统一入口**：废弃 API 直接写入，统一走 ETL 流程
