# `daily_bar / feature_wide` 修复实施方案

## 1. 目标

本方案用于修复 `daily_bar` 与 `feature_wide` 的增量更新故障，并给出后续可维护的统一实现办法。

本次修复要解决两个层次的问题：

1. **直接故障**：2026-04-09 之后通过 API 路径写入 `daily_bar` 的数据缺少 `cum_factor`，导致后续 `_close_adj` 和特征计算失败。该问题已经定位到 `api/routes/stocks.py` 的 `INSERT OR IGNORE INTO daily_bar` 语句漏掉了 `cum_factor` 和 `industry` 两列。fileciteturn5file0
2. **设计问题**：当前 `cum_factor` 是通过 `(1 + ret).cumprod()` 自造出来的，这不是严格意义上的复权因子，而且在增量模式下直接与旧 parquet `concat`，没有基于历史连续接续或重算，存在定义错误和断链风险。fileciteturn4file1turn4file3

---

## 2. 已确认的事实

### 2.1 现象

- `SQLite daily_bar` 最新日期到 `2026-04-15`，但 `cum_factor` 在 `2026-04-09` 之后全部为 `NULL`。fileciteturn5file0
- parquet 缓存只到 `2026-04-08`，并且其中 `cum_factor` 是有值的。fileciteturn4file4turn5file0
- 由于 `_close_adj = raw_close * cum_factor`，当 `cum_factor` 为 `NULL` 时，后续特征计算会产生 `NaN`，最终被 `dropna(...)` 清除。fileciteturn5file0

### 2.2 根因

项目中存在两个写入 `daily_bar` 的入口：

1. **ETL 入口**：`src/data_hub/etl_process.py`
   - 这条路径写入时包含 `cum_factor`。fileciteturn5file0
2. **API 入口**：`api/routes/stocks.py`
   - 这条路径的 `INSERT OR IGNORE INTO daily_bar` 只插入 16 列，缺少 `cum_factor` 和 `industry`。fileciteturn5file0

### 2.3 进一步问题

- `daily_bar` 当前使用 `PRIMARY KEY (date, code)`，配合 `INSERT OR IGNORE`。已经存在的坏行不会被后续正确流程覆盖修复。`_insert_or_ignore` 的实现与表 schema 已经明确说明了这一点。fileciteturn4file2
- 当前 `cum_factor` 的生成代码是：

  ```python
  df["ret"] = df["pctChg"] / 100
  df["cum_factor"] = (1 + df["ret"]).cumprod()
  ```

  这只是累计收益链，不是真正的复权因子。fileciteturn4file1

---

## 3. 修复原则

必须遵守以下原则：

1. **禁止多入口直接写 canonical 表**
   - `daily_bar` 只能有一个写入入口。
   - API 不能再自己手写 SQL 直接插入 `daily_bar`。API 只能调用统一 ETL 服务。

2. **先清坏数据，再回灌**
   - 不能只改代码而不清理已有坏数据。
   - 因为已有坏行会被 `INSERT OR IGNORE` 保留，导致看起来修了代码但数据库仍然不对。fileciteturn4file2

3. **短期先恢复系统可用，长期再重构 `cum_factor`**
   - 第一阶段先让 `daily_bar` 和 `feature_wide` 能恢复正常生产。
   - 第二阶段再重构 `cum_factor` 的定义与命名。

4. **增量写入必须支持修复**
   - 后续必须改成 upsert，而不是 `INSERT OR IGNORE`。

---

## 4. 改造总览

分为四个阶段实施。

### 阶段 A：立即止血

目标：阻止 API 继续写坏 `daily_bar`。

操作：

1. 找到 `api/routes/stocks.py` 中的 `_run_incremental_update(cfg)`。
2. 临时禁用其中直接执行 `INSERT OR IGNORE INTO daily_bar` 的代码。
3. 改成：
   - 要么直接报错并提示“请走 ETL 更新”；
   - 要么改成调用统一 ETL 方法。

### 阶段 B：修复统一写入链路

目标：保证以后所有 `daily_bar` 写入都走同一套逻辑。

操作：

1. 提取一个统一函数，例如：

   ```python
   def write_daily_bar(df: pd.DataFrame, cfg: dict, mode: str = "upsert") -> None:
       ...
   ```

2. `src/data_hub/etl_process.py` 和 `api/routes/stocks.py` 都调用这个函数。
3. 禁止任何地方手写针对 `daily_bar` 的独立 SQL 插入逻辑。

### 阶段 C：清理坏数据并回灌

目标：修复已经损坏的 `daily_bar` 和 `feature_wide`。

操作：

1. 备份数据库。
2. 删除 `2026-04-09` 之后的坏行；如果担心 3/30 开始的部分缺失也受影响，则从 `2026-03-30` 开始删除。此前调查已经显示自 3/30 起 `cum_factor` 非空率就已下降。fileciteturn3file0
3. 重新跑统一 ETL，回灌 `daily_bar`。
4. 重新增量生成 `feature_wide`。

### 阶段 D：重构 `cum_factor`

目标：去掉误导性定义，降低未来再次出错的概率。

操作：

1. 明确 `cum_factor` 的业务语义。
2. 如果它不是真实复权因子，就改名。
3. 如果需要真实复权逻辑，则改为真实复权方案，不再用累计收益链假装复权因子。fileciteturn4file1

---

## 5. 逐文件修改计划

## 5.1 修改 `api/routes/stocks.py`

### 5.1.1 当前问题

当前代码中存在类似如下逻辑：

```python
con.execute("""
    INSERT OR IGNORE INTO daily_bar
    (date, code, raw_open, raw_high, raw_low, raw_close, raw_volume, raw_amount,
     raw_pctChg, isST, tradestatus, raw_turn, raw_peTTM, raw_pbMRQ, raw_psTTM, raw_pcfNcfTTM)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", [...])
```

该语句缺少：

- `cum_factor`
- `industry`

这是本次直接故障点。fileciteturn5file0

### 5.1.2 修改要求

**不要继续补丁式地在 API 中手写插入列。**

应修改为以下两种方案之一。

#### 方案 A（推荐）：API 只调用 ETL

将 `_run_incremental_update(cfg)` 改为：

1. 只负责确定更新范围或触发任务；
2. 调用统一的 ETL 更新函数，例如：

```python
def _run_incremental_update(cfg: dict):
    from src.data_hub.pipeline import run_incremental_daily_bar_update
    run_incremental_daily_bar_update(cfg)
```

3. 删除 API 中所有直接对 `daily_bar` 的 `INSERT` / `to_sql` / `df_to_table` 代码。

#### 方案 B（过渡方案）：API 仍可写，但必须复用统一写库函数

如果短期内不能删除 API 的写库能力，则必须：

1. API 生成 DataFrame；
2. 调用统一的 `write_daily_bar()`；
3. 不允许 API 自己维护 `daily_bar` 字段列表。

### 5.1.3 禁止事项

低级 AI 在修改时禁止做以下事情：

- 不要简单把 `cum_factor` 多加一列后继续保留“双入口直接写库”设计。
- 不要让 API 和 ETL 各自维护一份字段清单。
- 不要继续使用 `INSERT OR IGNORE` 当成唯一的增量写入方式。

---

## 5.2 修改 `src/data_hub/etl_process.py`

### 5.2.1 当前状态

`_ingest_to_db()` 当前已有 `cum_factor`，字段列表如下：

```python
[
    "date", "code", "raw_open", "raw_high", "raw_low", "raw_close",
    "raw_volume", "raw_amount", "raw_pctChg", "raw_turn",
    "raw_peTTM", "raw_pbMRQ", "raw_psTTM", "raw_pcfNcfTTM",
    "cum_factor", "isST", "tradestatus", "industry",
]
```

该路径本身比 API 更完整。fileciteturn4file2turn5file0

### 5.2.2 必改内容

#### 改动 1：把 `_ingest_to_db()` 升级成 upsert

当前增量逻辑是：

- `INSERT OR IGNORE`
- 已存在主键行不会更新

这不利于修复脏数据。应改为：

- `INSERT ... ON CONFLICT(date, code) DO UPDATE SET ...`

SQLite 支持这种写法。

#### 改动 2：单独封装 `daily_bar` 的 upsert 方法

建议新建一个函数：

```python
def _upsert_daily_bar(con, df: pd.DataFrame) -> None:
    ...
```

这个函数负责：

1. 固定 canonical 列顺序；
2. 补齐缺失列；
3. 执行 `ON CONFLICT DO UPDATE`。

### 5.2.3 推荐实现

```python
def _upsert_daily_bar(con, df: pd.DataFrame) -> None:
    cols = [
        "date", "code", "raw_open", "raw_high", "raw_low", "raw_close",
        "raw_volume", "raw_amount", "raw_pctChg", "raw_turn",
        "raw_peTTM", "raw_pbMRQ", "raw_psTTM", "raw_pcfNcfTTM",
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
```

### 5.2.4 修改 `_ingest_to_db()` 的调用逻辑

将当前：

```python
con.df_to_table(
    "daily_bar", insert_df,
    chunksize=5000, method=_insert_or_ignore,
)
```

替换为：

```python
_upsert_daily_bar(con, ingest_df)
```

### 5.2.5 注意事项

- 如果数据库包装器 `con` 不支持原生 `executemany`，则要取到底层 sqlite connection。
- 不要混用“部分列插入 + 忽略冲突”的旧模式。
- `available = [c for c in daily_bar_cols if c in df.columns]` 这种“只取交集”的写法不适合 canonical 层。应该改成“补齐再对齐”。

---

## 5.3 修改 `src/data_hub/baostock_client.py`

### 5.3.1 当前问题

当前抓单只股票时：

```python
df["ret"] = df["pctChg"] / 100
df["cum_factor"] = (1 + df["ret"]).cumprod()
```

增量模式下：

```python
merged = pd.concat([old_df, df], ignore_index=True)
merged = merged.drop_duplicates(subset=["date"], keep="last")
merged = merged.sort_values("date").reset_index(drop=True)
```

没有在合并后重新计算 `cum_factor`。这意味着新段的 `cum_factor` 是从增量起点重新开始的，与历史链不连续。fileciteturn4file3

### 5.3.2 短期修法

#### 方案 A：合并后整只股票重算累计链

这是最简单和最稳的短期方案。

```python
merged = pd.concat([old_df, df], ignore_index=True)
merged = merged.drop_duplicates(subset=["date"], keep="last")
merged = merged.sort_values("date").reset_index(drop=True)
merged["ret"] = merged["pctChg"] / 100
merged["cum_factor"] = (1 + merged["ret"]).cumprod()
merged.to_parquet(fp, index=False)
```

优点：

- 最容易实现；
- 不会出现增量段从 1 重新起算的问题。

缺点：

- 依然只是累计收益链，不是真复权因子。

#### 方案 B：增量接续旧尾值

如果担心全量重算太慢，可以接续旧值：

```python
old_df = old_df.sort_values("date").copy()
df = df.sort_values("date").copy()

old_df["ret"] = old_df["pctChg"] / 100
last_factor = old_df["cum_factor"].dropna().iloc[-1]

df["ret"] = df["pctChg"] / 100
df["cum_factor"] = last_factor * (1 + df["ret"]).cumprod()

merged = pd.concat([old_df, df], ignore_index=True)
merged = merged.drop_duplicates(subset=["date"], keep="last")
merged = merged.sort_values("date").reset_index(drop=True)
```

### 5.3.3 长期修法

如果业务上真的需要复权因子：

1. 不能再用 `(1 + ret).cumprod()` 充当 `cum_factor`；
2. 应改为：
   - 直接拉取真实前复权/后复权价格；或者
   - 引入真实复权因子来源；或者
   - 如果只是连续价格链，则改名为 `cum_return_index` / `close_chain`。

### 5.3.4 推荐命名变更

建议中长期把：

- `cum_factor` 改名为 `cum_return_index`

并同步修改依赖代码，避免概念误导。

---

## 5.4 修改特征工程入口（可选但推荐）

### 5.4.1 为什么要改

虽然这次直接故障点不在 `build_alpha158()`，但当前特征流程对上游坏数据太脆弱：

- `cum_factor` 一坏；
- `_close_adj` 就坏；
- 某些特征列全 NaN；
- 最终整批日期被删掉。

### 5.4.2 建议修改

#### 改动 1：对关键输入列做前置检查

在进入 `build_alpha158()` 之前，先检查：

- `raw_close`
- `cum_factor`
- `_close_adj`

例如：

```python
def validate_feature_inputs(df: pd.DataFrame) -> None:
    critical = ["raw_close", "cum_factor"]
    for c in critical:
        if c not in df.columns:
            raise ValueError(f"缺少关键列: {c}")

    bad = df.groupby("date")["cum_factor"].apply(lambda s: s.notna().mean())
    if (bad < 0.5).any():
        dates = bad[bad < 0.5].index.tolist()
        raise ValueError(f"cum_factor 在以下日期缺失过多: {dates[:10]}")
```

#### 改动 2：把错误信息打清楚

不要让系统只是静默地产出“feature_wide 没更新”。
应明确报：

- 哪些日期关键列全空
- 可能是上游 `daily_bar` 写坏

#### 改动 3：保留中间诊断快照

生成临时 parquet，如：

- `debug/daily_bar_slice_before_feature.parquet`
- `debug/alpha158_raw_before_dropna.parquet`

这样以后出故障时不用重复猜。

---

## 6. 数据修复执行步骤

下面是必须按顺序执行的修复步骤。

### 6.1 备份

先备份 SQLite：

```bash
cp data/rearmirror.db data/rearmirror.db.bak_$(date +%Y%m%d_%H%M%S)
```

如果路径不同，请替换成真实数据库路径。

### 6.2 停止错误入口

1. 暂时禁用 API `/update` 对 `daily_bar` 的直接写入。
2. 确认不会再有新请求把坏数据写进去。

### 6.3 修改代码并完成本地测试

按上面第 5 节完成代码修改。

### 6.4 删除坏数据

#### 保守方案

只删除已确认损坏区间：

```sql
DELETE FROM daily_bar
WHERE DATE(date) >= DATE('2026-04-09');
```

#### 稳妥方案

如果你认为 `2026-03-30` 开始的部分缺失也属于同一批问题，则删除：

```sql
DELETE FROM daily_bar
WHERE DATE(date) >= DATE('2026-03-30');
```

此前调查中，从 3/30 开始 `cum_factor` 非空率已经显著下降。fileciteturn3file0

### 6.5 重新回灌 `daily_bar`

执行统一 ETL 更新流程：

1. 重新抓取对应日期区间；
2. 更新 parquet cache；
3. 统一写入 `daily_bar`；
4. 确认 `cum_factor` 和 `industry` 均存在。

### 6.6 验证 `daily_bar`

执行以下 SQL 检查：

```sql
SELECT DATE(date) AS d,
       COUNT(*) AS total,
       SUM(CASE WHEN cum_factor IS NOT NULL THEN 1 ELSE 0 END) AS non_null,
       ROUND(100.0 * SUM(CASE WHEN cum_factor IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_non_null
FROM daily_bar
WHERE DATE(date) >= DATE('2026-03-30')
GROUP BY DATE(date)
ORDER BY DATE(date);
```

检查目标：

- 2026-04-09 之后不再是 0%。
- 非空率应恢复到合理水平。

### 6.7 删除并重建 `feature_wide`

因为 4/9 之后此前本来就没算对，必须重跑。

如果是按增量重建：

1. 删除 `feature_wide` 中受影响区间；
2. 从重新修好的 `daily_bar` 生成增量特征。

建议删除区间与 `daily_bar` 删除区间保持一致。

例如：

```sql
DELETE FROM feature_wide
WHERE DATE(date) >= DATE('2026-04-09');
```

或者：

```sql
DELETE FROM feature_wide
WHERE DATE(date) >= DATE('2026-03-30');
```

### 6.8 重新生成特征

重跑增量特征流程后，验证：

```sql
SELECT MIN(DATE(date)), MAX(DATE(date)), COUNT(*)
FROM feature_wide;
```

目标：

- 最新日期推进到 `2026-04-15`；
- 行数符合该区间交易日规模；
- 不再停在 `2026-04-08`。

---

## 7. 验证清单

低级 AI 执行完修改后，必须逐项验证。以下任一项不通过，都视为修复失败。

### 7.1 代码级验证

- [ ] `api/routes/stocks.py` 中不再存在手写 `INSERT OR IGNORE INTO daily_bar`。
- [ ] `daily_bar` 的写入统一走一个公共函数。
- [ ] 公共写入函数使用 upsert，而不是 ignore。
- [ ] 公共写入函数会补齐 canonical 列。
- [ ] `cum_factor` 在增量 parquet 合并后会重新计算或正确接续。

### 7.2 数据级验证

- [ ] `daily_bar` 在 2026-04-09 ~ 2026-04-15 之间 `cum_factor` 非空率恢复正常。
- [ ] `daily_bar` 在同一区间 `industry` 不再异常缺失。
- [ ] parquet cache 最新日期至少与 `daily_bar` 一致。
- [ ] `feature_wide` 最新日期推进到 `2026-04-15`。

### 7.3 行为级验证

- [ ] 重复执行一次增量更新，不会再次把 `cum_factor` 写成 NULL。
- [ ] 重复执行一次相同日期区间回灌，数据结果不应变坏。
- [ ] API 和 ETL 任一入口触发更新，结果都一致。

---

## 8. 回滚方案

如果修改后出现问题，按以下方式回滚。

### 8.1 回滚数据库

使用备份文件恢复：

```bash
mv data/rearmirror.db.bak_YYYYMMDD_HHMMSS data/rearmirror.db
```

### 8.2 回滚代码

回退以下文件：

- `api/routes/stocks.py`
- `src/data_hub/etl_process.py`
- `src/data_hub/baostock_client.py`
- 任何新建的 pipeline / writer 工具文件

### 8.3 回滚条件

满足以下任一条则回滚：

- `daily_bar` 行数异常减少；
- 大量字段被错误覆盖为 `NULL`；
- `feature_wide` 无法重建；
- 增量更新报错且无法短时间定位。

---

## 9. 推荐的最小实施版本

如果时间紧，只做最关键修复，按下面顺序完成。

### 最小版本 V1

1. 禁用 API 直接写 `daily_bar`。
2. 所有更新统一走 `etl_process.py`。
3. 删除 `2026-04-09` 之后的 `daily_bar` 坏行。
4. 重新回灌 `daily_bar`。
5. 删除 `feature_wide` 对应区间并重算。

这能最快恢复生产可用。

### 加强版本 V2

在 V1 基础上再做：

1. 把 `INSERT OR IGNORE` 改成 upsert。
2. 改造 `baostock_client.py`，让 `cum_factor` 在增量合并后重算。
3. 在特征工程前增加关键输入列校验。

### 完整版本 V3

在 V2 基础上再做：

1. 重构 `cum_factor` 的业务定义；
2. 如果不是复权因子，则改名为 `cum_return_index`；
3. 清理项目内所有“把累计收益链当复权因子”的代码和注释。

---

## 10. 给执行 AI 的明确指令

下面这段可以直接交给低级 AI 执行。

### 指令文本

1. 先全局搜索所有写入 `daily_bar` 的代码，确认只保留一个公共写入函数。
2. 删除或改造 `api/routes/stocks.py` 中直接 `INSERT OR IGNORE INTO daily_bar` 的逻辑，不允许 API 再直接写 canonical 表。
3. 在 `src/data_hub/etl_process.py` 中实现 `_upsert_daily_bar()`，使用 `ON CONFLICT(date, code) DO UPDATE`。
4. 所有写入 `daily_bar` 的地方统一调用 `_upsert_daily_bar()`。
5. 在 `src/data_hub/baostock_client.py` 中，增量合并 parquet 后重新计算 `cum_factor`，不要只对新增切片单独 `cumprod()` 后直接拼接。
6. 备份数据库。
7. 删除 `daily_bar` 中 `2026-04-09` 之后的坏数据；如果验证发现 `2026-03-30` 之后也异常，则从 `2026-03-30` 开始删除。
8. 重新执行统一 ETL 回灌 `daily_bar`。
9. 检查 `daily_bar` 中 `cum_factor` 按日期的非空率，确认 2026-04-09 之后恢复正常。
10. 删除 `feature_wide` 中相同日期区间的数据，并重新执行增量特征构建。
11. 验证 `feature_wide` 最新日期达到 `2026-04-15`。
12. 补充自动化测试，覆盖：
    - API 更新
    - ETL 更新
    - 重复增量更新
    - 同主键行修复更新
13. 输出修改的文件清单、SQL 执行记录、验证结果。

---

## 11. 补充说明

本次直接故障已经明确来自 API 写入入口漏列。fileciteturn5file0 但同时，当前 `cum_factor` 的设计仍然存在长期风险，因为它只是累计收益链，不是真实复权因子。fileciteturn4file1 所以不能只修 API 漏列这一处就结束，至少还要完成统一写入入口和 upsert 两项治理，否则未来仍可能出现“坏数据先写入、后续无法修复”的同类事故。`daily_bar` 当前使用主键 `(date, code)` 并配合 `INSERT OR IGNORE`，已经证明了这一点。fileciteturn4file2
