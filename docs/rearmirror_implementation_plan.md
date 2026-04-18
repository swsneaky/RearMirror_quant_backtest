# RearMirror 修复与重构实施计划（可直接交给低级 AI 执行）

## 0. 目标

本计划解决两个核心问题：

1. **更新链断裂**：`daily_bar`、`feature_wide`、`label_wide`、`predictions` 不能自动按依赖顺序更新。
2. **`cum_factor` 设计与写入问题**：
   - 历史故障：API 写 `daily_bar` 时漏掉 `cum_factor`，导致 2026-04-09 之后该列为 NULL。
   - 长期设计：当前 `cum_factor = (1 + ret).cumprod()`，它不是“真实复权因子”，只是“累计收益链”。

---

## 1. 先做什么，后做什么

严格按下面顺序执行，不要跳步：

### Phase 1：止血修复（当天完成）
1. 禁止 API 直接向 `daily_bar` 写原始 SQL。
2. 统一让 API 调用 ETL 的统一入库函数。
3. 把 `daily_bar` 的写入策略统一为 **upsert**，不能再用 `INSERT OR IGNORE`。
4. 删除已经写坏的 `daily_bar` 脏数据，并回灌正确数据。
5. 重建 `feature_wide` 增量。
6. 补建 `label_wide`。

### Phase 2：链路修复（1~2 天）
1. 增加统一入口 `run_daily_update()`。
2. 抽取独立的 `run_label_pipeline()`。
3. 把每日更新串成一个完整流程：
   `daily_bar -> feature_wide -> label_wide -> predictions`
4. 增加 freshness 校验。

### Phase 3：长期治理（后续迭代）
1. 重命名 `cum_factor`。
2. 明确它只是累计收益链，而不是真实复权因子。
3. 后续如有条件，引入真实复权因子或真实复权价。

---

## 2. 已确认的问题（作为实施依据）

### 2.1 两个写入入口导致数据不一致
项目里至少存在两个写 `daily_bar` 的入口：

- `src/data_hub/etl_process.py`：有 `cum_factor`
- `api/routes/stocks.py`：缺少 `cum_factor`

因此 API 写入的数据会把 `daily_bar.cum_factor` 留空。

### 2.2 2026-04-09 之后 `cum_factor` 全 NULL
这会导致：

- `_close_adj = raw_close * cum_factor` 变成 NaN
- `build_alpha158()` 后续 `dropna(...)` 把这些行全部删掉
- `feature_wide` 只能更新到 2026-04-08

### 2.3 当前 `cum_factor` 不是复权因子
当前逻辑：

```python
ret = pctChg / 100
cum_factor = (1 + ret).cumprod()
```

这只是累计收益链，不是真实复权因子。

### 2.4 更新链断裂
当前各层更新是分裂的：

- API `/api/stocks/update` 只更新 `daily_bar`
- `feature_wide` 要手动跑
- `label_wide` 嵌在 neutralize 流程里，没有独立入口
- `predictions` 更滞后

这会造成“上游新、下游旧”的半坏状态。

---

## 3. Phase 1：止血修复

## 3.1 修改目标

### 必须达到的结果
1. API 不再自己拼 SQL 写 `daily_bar`。
2. `daily_bar` 只有一个 canonical 写入入口。
3. 该入口支持 **upsert**。
4. 历史坏数据可被删除并重新灌入。

---

## 3.2 修改文件一：`api/routes/stocks.py`

## 目标
废弃 API 内部手写的 `INSERT OR IGNORE INTO daily_bar (...)`。

## 操作要求

### 旧行为（必须删除/停用）
API 内部直接：

```python
con.execute("""
    INSERT OR IGNORE INTO daily_bar (...)
    VALUES (...)
""")
```

### 新行为（必须改成）
API 只负责：

1. 下载增量数据
2. 组装成 DataFrame
3. 调用统一函数 `ingest_daily_bar_df(df, cfg, update_mode="incremental")`

### 改造原则
- API **不能**再直接碰 `daily_bar` SQL
- API 只做 orchestrator，不做 canonical table writer

## 要求低级 AI 实现的伪代码

```python
from src.data_hub.etl_process import ingest_daily_bar_df


def _run_incremental_update(cfg: dict):
    # 1. 下载所有需要更新股票的数据
    # 2. 拼成一个总 DataFrame all_df
    # 3. 调统一入库
    ingest_daily_bar_df(all_df, cfg, update_mode="incremental")
    return {
        "status": "ok",
        "rows": len(all_df),
    }
```

## 验收标准
- 项目中不再存在 API 直接 `INSERT INTO daily_bar` 的代码
- `grep -R "INSERT.*daily_bar" -n api src` 不应再出现 API 里的直接写入 SQL

---

## 3.3 修改文件二：`src/data_hub/etl_process.py`

## 目标
提供统一的 `daily_bar` 入库函数，并把写入语义改为 upsert。

## 要求

### 1）新增统一函数
必须新增或明确暴露：

```python
def ingest_daily_bar_df(df: pd.DataFrame, cfg: dict, update_mode: str = "incremental") -> None:
    ...
```

它内部要完成：

1. `_apply_raw_prefix(df)`
2. `_join_industry(df, cfg)`
3. `_ensure_cum_factor(df)`
4. 排序：`sort_values(["code", "date"])`
5. upsert 到 `daily_bar`

---

### 2）增加 `_ensure_cum_factor(df)`
新增一个明确函数：

```python
def _ensure_cum_factor(df: pd.DataFrame) -> pd.DataFrame:
    ...
```

### 规则
- 如果传入数据已有 `cum_factor`，先保留，但允许重算
- 如果没有 `cum_factor`，则根据 `raw_pctChg` 计算
- 计算必须按 `code, date` 排序后，按股票分组计算
- 不能跨股票做 cumprod

### 实现要求

```python

def _ensure_cum_factor(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["date"] = pd.to_datetime(out["date"])
    out = out.sort_values(["code", "date"]).reset_index(drop=True)

    if "raw_pctChg" in out.columns:
        # raw_pctChg 统一约定为小数收益率，例如 0.01 表示 1%
        out["ret"] = pd.to_numeric(out["raw_pctChg"], errors="coerce")
        out["cum_factor"] = (
            1.0 + out["ret"].fillna(0.0)
        ).groupby(out["code"]).cumprod()
        out = out.drop(columns=["ret"], errors="ignore")

    return out
```

### 注意
这一步只是**短期修复**，不是最终“真实复权因子”方案。

---

### 3）把 `_insert_or_ignore` 改成 upsert
不要继续使用：

```python
INSERT OR IGNORE INTO daily_bar ...
```

必须改成：

```sql
INSERT INTO daily_bar (...) VALUES (...)
ON CONFLICT(date, code) DO UPDATE SET
    raw_open=excluded.raw_open,
    raw_high=excluded.raw_high,
    raw_low=excluded.raw_low,
    raw_close=excluded.raw_close,
    raw_volume=excluded.raw_volume,
    raw_amount=excluded.raw_amount,
    raw_pctChg=excluded.raw_pctChg,
    raw_turn=excluded.raw_turn,
    raw_peTTM=excluded.raw_peTTM,
    raw_pbMRQ=excluded.raw_pbMRQ,
    raw_psTTM=excluded.raw_psTTM,
    raw_pcfNcfTTM=excluded.raw_pcfNcfTTM,
    cum_factor=excluded.cum_factor,
    isST=excluded.isST,
    tradestatus=excluded.tradestatus,
    industry=excluded.industry
```

### 推荐函数名

```python
def _upsert_daily_bar(table, conn, keys, data_iter):
    ...
```

### 验收标准
- `daily_bar` 中同一 `(date, code)` 的已有脏值可以被新值覆盖
- 不再因为旧坏行存在而无法修复

---

## 3.4 数据修复操作

## 目标
删除已坏的 `daily_bar` 行，然后用正确入口重灌。

### 先备份数据库
要求低级 AI 先执行：

```bash
cp data/rearmirror.db data/rearmirror.db.bak_$(date +%Y%m%d_%H%M%S)
```

### 删除坏数据
如果只确认 2026-04-09 以后坏掉，则执行：

```sql
DELETE FROM daily_bar
WHERE DATE(date) >= DATE('2026-04-09');
```

如果怀疑 2026-03-30 起已部分异常，则更稳妥的做法：

```sql
DELETE FROM daily_bar
WHERE DATE(date) >= DATE('2026-03-30');
```

### 回灌数据
必须使用**统一入口**重新跑：

1. 重新下载/加载 2026-03-30 之后原始数据
2. 调用 `ingest_daily_bar_df(...)`
3. 验证 `cum_factor` 不再为空

### SQL 验收

```sql
SELECT DATE(date) AS d, COUNT(*) AS total,
       SUM(CASE WHEN cum_factor IS NOT NULL THEN 1 ELSE 0 END) AS non_null
FROM daily_bar
WHERE DATE(date) >= DATE('2026-03-30')
GROUP BY DATE(date)
ORDER BY d;
```

### 通过条件
- 2026-04-09 及之后日期 `non_null > 0`
- 理想状态：除停牌/异常个股外，大多数股票非空

---

## 3.5 重建 `feature_wide`

## 目标
在 `daily_bar` 修复后，重新补齐特征。

### 当前规则
特征依赖 `daily_bar`，最大窗口为 60，当前逻辑有 warmup + sentinel dropna。

### 修复执行顺序
1. 先确认 `daily_bar` 已修复
2. 再跑 `run_raw_feature_pipeline()`
3. 特征加载时，从 `feature_wide.max(date)` 往前取 `max_window + 10` 个交易日作为预热
4. 计算后只保留新日期
5. upsert 到 `feature_wide`

### 低级 AI 要检查的点
- `feature_wide` 写入也要支持 upsert
- 若旧逻辑仍是 append + ignore，要同步改成 upsert

### 验收 SQL

```sql
SELECT MAX(DATE(date)) FROM feature_wide;
SELECT MAX(DATE(date)) FROM daily_bar;
```

### 通过条件
- `feature_wide.max(date) == daily_bar.max(date)`

---

## 3.6 补建 `label_wide`

## 目标
在特征更新后，让标签也更新到合理的最新日期。

### 注意
如果 horizon=5，则标签天然滞后 5 天。
也就是说：

- 如果 `daily_bar.max(date) = 2026-04-17`
- 那么 `label_wide.max(date)` 的合理上限大约是 `2026-04-12`

### 现阶段最低要求
即便暂时不重构，也必须手动补跑当前 label 生成流程，让 `label_wide` 不再停留在旧日期。

---

## 4. Phase 2：更新链修复

## 4.1 新增统一编排入口

新增一个统一更新函数，例如放在 `pipeline.py`：

```python
def run_daily_update(cfg: dict, run_prediction: bool = False):
    """统一每日更新入口"""
```

### 执行顺序固定为
1. `run_stock_update(cfg)` 或 `_run_incremental_update(cfg)`
2. `run_raw_feature_pipeline(cfg)`
3. `run_label_pipeline(cfg)`
4. 可选 `run_prediction_pipeline(cfg)`

### 中间不能跳步
如果任一层失败，必须立即抛异常并终止后续步骤。

---

## 4.2 抽取独立标签入口 `run_label_pipeline()`

## 目标
把标签更新从 neutralize 流程里独立出来。

### 必须新增

```python
def run_label_pipeline(cfg: dict):
    ...
```

### 行为要求
1. 读取 `feature_wide` 或 `daily_bar`
2. 按配置生成标签
3. 只重算一个安全窗口，而不是全表重算
4. upsert 到 `label_wide`

### 建议增量策略
若 horizon=5：

```python
old_label_max = get_label_max_date()
recalc_start = old_label_max - 7 days   # 或 old_label_max 往前 horizon+2 个交易日
load data from recalc_start onward
recompute labels
only keep rows whose future label is fully available
upsert into label_wide
```

### 原则
- 不要只从 `old_label_max + 1` 开始直接算
- 因为未来收益标签会受边界影响

---

## 4.3 增加 freshness 校验

统一入口执行完后，必须打印并校验：

```python
daily_max = ...
feature_max = ...
label_max = ...
pred_max = ...
```

### 校验规则

#### 规则 1
`feature_max == daily_max`

#### 规则 2
`label_max <= daily_max - horizon`

#### 规则 3
若 `run_prediction=True`，则 `pred_max <= label_max`

### 示例输出

```text
daily_bar     2026-04-17
feature_wide  2026-04-17
label_wide    2026-04-12
predictions   2026-04-12
STATUS: OK
```

### 若不满足
直接抛异常，不允许假装成功。

---

## 5. Phase 3：`cum_factor` 长期重构

## 5.1 短期定义
短期内承认：

- 当前 `cum_factor` 只是“累计收益链”
- 不是复权因子

### 建议短期动作
在代码注释、文档、字段说明里明确写清楚。

---

## 5.2 中期动作：重命名字段

建议新字段名：

- `cum_return_index`
- 或 `price_chain`

### 迁移策略
1. 先保留旧字段 `cum_factor`
2. 新增同值字段 `cum_return_index`
3. 逐步把下游 `_close_adj` / 特征逻辑切换到新字段
4. 等全链路稳定后，再考虑删除旧字段

---

## 5.3 长期动作：引入真实复权方案

如果未来要做严谨的复权价格分析，应引入：

1. 真实复权因子
2. 或数据源直接提供的前复权/后复权价格

在没有真实复权数据前，不要把当前字段宣传为“复权因子”。

---

## 6. 低级 AI 的详细执行清单

## Step 1：搜索并删除所有 direct write 入口
执行：

```bash
grep -R "INSERT.*daily_bar\|df_to_table(.*daily_bar\|to_sql(.*daily_bar" -n api src
```

### 目标
- 找到所有 `daily_bar` 写入入口
- 最终只保留 **统一入库函数** 作为 canonical writer

---

## Step 2：改 `api/routes/stocks.py`

### 任务
- 删除 API 内直接写 `daily_bar` 的 SQL
- 改为收集 DataFrame 后调用 `ingest_daily_bar_df()`

### 完成后检查
- API 代码中不再出现 `INSERT INTO daily_bar`

---

## Step 3：改 `src/data_hub/etl_process.py`

### 任务
- 新增 `ingest_daily_bar_df()`
- 新增 `_ensure_cum_factor()`
- 把 `_insert_or_ignore` 改为 `_upsert_daily_bar`
- 更新 `_ingest_to_db()` 调用逻辑

### 完成后检查
- ETL 可处理 API 输入的 DataFrame
- 重复写入同一 `(date, code)` 时会更新，而不是忽略

---

## Step 4：备份并清理坏数据

### 任务
- 备份 SQLite
- 删除坏日期范围内的 `daily_bar`

### 完成后检查
```sql
SELECT COUNT(*) FROM daily_bar WHERE DATE(date) >= DATE('2026-04-09');
```
应为 0（或按你选择的起始日期检查）。

---

## Step 5：重新跑 `daily_bar` 更新

### 任务
- 用 API 或脚本重新下载 2026-03-30 之后的数据
- 走统一入口入库

### 完成后检查
```sql
SELECT DATE(date) AS d,
       COUNT(*) AS total,
       SUM(CASE WHEN cum_factor IS NOT NULL THEN 1 ELSE 0 END) AS non_null
FROM daily_bar
WHERE DATE(date) >= DATE('2026-03-30')
GROUP BY DATE(date)
ORDER BY d;
```

### 通过条件
- 2026-04-09 以后 `non_null` 不再是 0

---

## Step 6：重跑特征

### 任务
- 跑 `run_raw_feature_pipeline()`
- 确认补齐到最新 `daily_bar` 日期

### 完成后检查
```sql
SELECT MAX(DATE(date)) FROM daily_bar;
SELECT MAX(DATE(date)) FROM feature_wide;
```

---

## Step 7：新增并运行 `run_label_pipeline()`

### 任务
- 从 neutralize 流程中拆出标签生成入口
- 增量更新 `label_wide`

### 完成后检查
```sql
SELECT MAX(DATE(date)) FROM label_wide;
```

### 通过条件
- `label_wide` 更新到 `daily_bar.max(date) - horizon` 附近

---

## Step 8：新增统一入口 `run_daily_update()`

### 任务
- 串联 `daily_bar -> feature_wide -> label_wide -> predictions`
- 增加 freshness 校验

### 完成后检查
运行一次后，必须打印完整状态摘要。

---

## 7. 验收标准（必须全部满足）

### A. 结构验收
- [ ] 项目中只有一个 canonical `daily_bar` 写入入口
- [ ] API 不再直接写 `daily_bar`
- [ ] `daily_bar` 使用 upsert
- [ ] `label_wide` 有独立入口
- [ ] 有统一的 `run_daily_update()`

### B. 数据验收
- [ ] `daily_bar` 的 2026-04-09 之后 `cum_factor` 不再全空
- [ ] `feature_wide.max(date) == daily_bar.max(date)`
- [ ] `label_wide.max(date)` 合理滞后于 `daily_bar.max(date)`
- [ ] 重复运行更新流程不会产生更多脏数据

### C. 行为验收
- [ ] 同一天重复执行 `run_daily_update()` 不应报错
- [ ] 若 `daily_bar` 无新数据，则 `feature_wide` / `label_wide` 应安全跳过或仅做必要补算
- [ ] 任一层失败时，后续层不继续执行

---

## 8. 回滚方案

如果任一步骤失败，按以下顺序回滚：

1. 停止所有自动/手动更新操作
2. 用备份数据库恢复：

```bash
cp data/rearmirror.db.bak_YYYYMMDD_HHMMSS data/rearmirror.db
```

3. 回退最近修改的 Python 文件
4. 再次确认 `daily_bar` / `feature_wide` / `label_wide` 的最大日期
5. 只在单独测试环境重新试跑

---

## 9. 最终目标

最终用户只需要运行一个入口，例如：

```bash
python pipeline.py daily_update
```

系统自动完成：

1. 更新 `daily_bar`
2. 更新 `feature_wide`
3. 更新 `label_wide`
4. 可选更新 `predictions`
5. 打印状态摘要
6. 若任何层失败，直接报错退出

这才算真正修复“更新链断裂”问题。
