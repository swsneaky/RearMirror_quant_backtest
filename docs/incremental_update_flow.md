# RearMirror 增量更新流程文档

## 概述

本文档描述 RearMirror 项目的四层数据增量更新流程：
1. 原始股票日线下载 (BaoStock API)
2. 入库股票日线 (daily_bar 表)
3. 特征矩阵 (feature_wide 表)
4. 标签矩阵 (label_wide 表)

---

## 1. 原始股票日线下载

### 入口
- API: `POST /api/stocks/update`
- 函数: `api/routes/stocks.py::_run_incremental_update()`

### 流程
```
1. 查询 daily_bar 获取每只股票最后日期
   SELECT code, MAX(date) FROM daily_bar GROUP BY code

2. 计算增量范围
   last_date < today → 需要更新
   start = last_date + 1 day

3. 调用 BaoStock API 下载
   bs.query_history_k_data_plus(code, fields, start_date=start, end_date=today)

4. 返回 DataFrame (16 列，无 raw_ 前缀)
   date, code, open, high, low, close, volume, amount,
   pctChg, isST, tradestatus, turn, peTTM, pbMRQ, psTTM, pcfNcfTTM
```

### 问题
- 无独立缓存层，直接从 API 拉取
- 依赖 BaoStock 服务可用性
- 有反爬限制（随机休眠 0.2-0.5s/股票）

---

## 2. 入库股票日线 (daily_bar)

### 入口
- 统一函数: `src/data_hub/etl_process.py::ingest_daily_bar_df()`
- 被 API 和 ETL 流程共同调用

### 流程
```
1. 应用 raw_ 前缀
   open → raw_open, close → raw_close, ...

2. 关联行业映射
   _join_industry(df, cfg) → 从 industry_map 表关联

3. 计算 cum_factor
   _ensure_cum_factor(df):
     df["ret"] = df["raw_pctChg"] / 100
     df["cum_factor"] = (1 + df["ret"]).cumprod()
   
   ⚠️ 注意: 这是累计收益链，不是真实复权因子

4. 执行 upsert
   INSERT INTO daily_bar (...) VALUES (...)
   ON CONFLICT(date, code) DO UPDATE SET ...
```

### Schema (18 列)
```sql
daily_bar (
    date, code,                           -- 主键
    raw_open, raw_high, raw_low, raw_close,
    raw_volume, raw_amount, raw_pctChg, raw_turn,
    raw_peTTM, raw_pbMRQ, raw_psTTM, raw_pcfNcfTTM,
    cum_factor, isST, tradestatus, industry
)
PRIMARY KEY (date, code)
```

### 增量语义
- **upsert**: 新主键插入，已存在主键更新
- 支持修复历史脏数据
- 不删除旧数据

---

## 3. 特征矩阵 (feature_wide)

### 入口
- Pipeline: `pipeline.py::run_raw_feature_pipeline()`
- 核心函数: `src/feature_engine.py::build_alpha158()`

### 增量逻辑 (DB-first)
```
1. 获取 feature_wide 当前状态
   SELECT MAX(date) FROM feature_wide → old_max

2. 获取 daily_bar 最新日期
   SELECT MAX(date) FROM daily_bar → daily_max

3. 计算新交易日
   SELECT DISTINCT date FROM daily_bar 
   WHERE date > old_max → new_dates

4. 如果无新日期 → 跳过，返回现有数据

5. 如果有新日期:
   a. 计算预热起点
      warmup_start = daily_max - (max_window + 10) 天
   
   b. 加载切片数据
      SELECT * FROM daily_bar WHERE date >= warmup_start
   
   c. 计算因子 (build_alpha158)
      - kline: KMID, KUP, KLOW, KSFT, ...
      - rolling: ROC5, ROC10, MA5, MA10, ...
      - technical: MACD, RSI, KDJ, ...
      - turnover: TURN5, TURN10, ...
      - valuation: PE_TTM, PB_MRQ, ...
   
   d. 仅保留新日期行 (date > old_max)
   
   e. 追加到 feature_wide
      INSERT INTO feature_wide (...) VALUES (...)
      ON CONFLICT(date, code) DO UPDATE ...
```

### 当前因子 (230 列)
- kline: 12 个
- rolling: 50 个 (5 种 × 10 窗口)
- rolling_ext: 30 个
- technical: 78 个
- turnover: 30 个
- valuation: 30 个

### 问题
- 增量逻辑依赖 feature_wide 有数据才能判断 old_max
- 无数据时走全量构建
- 预热窗口需要重新计算 (max_window + 10 天)

---

## 4. 标签矩阵 (label_wide)

### 入口
- Pipeline: `pipeline.py::run_neutralize_pipeline()` 内部调用
- 函数: `src/label_gen.py::generate_labels()`

### 当前配置
```yaml
label:
  name: label_5d_ret
  horizon: 5
  method: pctChg_sum  # 或 close_ratio
```

### 生成逻辑
```python
# 未来 5 日收益
shifted = df.groupby("code")["raw_pctChg"].shift(-5)
label_values = shifted.groupby(df["code"]).rolling(5).sum()

# 或收盘价比率
future_close = df.groupby("code")["raw_close"].shift(-5)
label_values = future_close / df["raw_close"] - 1

# 删除无标签行
df = df.dropna(subset=[label_name])
```

### 增量逻辑
```
⚠️ 当前无独立增量入口！

标签生成嵌入在 run_neutralize_pipeline() 中：
1. 加载 feature_wide
2. 调用 generate_labels()
3. 保存到 label_wide

这意味着:
- 更新 feature_wide 后必须重跑 neutralize 流程
- label_wide 无法独立增量更新
```

### 天然滞后
- 5 日标签需要未来 5 天数据
- 今天 (2026-04-18) 最多算到 2026-04-13
- label_wide 最新日期 = daily_bar 最新日期 - horizon 天

---

## 流程依赖图

```
BaoStock API
     │
     ▼
┌─────────────┐
│ daily_bar   │ ← ingest_daily_bar_df() 统一入库
└─────────────┘
     │
     ▼
┌─────────────┐
│ feature_wide│ ← build_alpha158() 增量计算因子
└─────────────┘
     │
     ▼
┌─────────────┐
│ label_wide  │ ← generate_labels() (嵌入 neutralize 流程)
└─────────────┘
     │
     ▼
┌─────────────┐
│ predictions │ ← 回测流程
└─────────────┘
```

---

## 当前状态 (2026-04-18)

| 数据层 | 最新日期 | 状态 |
|--------|----------|------|
| daily_bar | 2026-04-17 | ✅ 最新 |
| feature_wide | 2026-04-17 | ✅ 最新 |
| label_wide | 2026-03-31 | ⚠️ 落后 17 天 |
| predictions | 2026-03-11 | ❌ 旧数据 |

---

## 问题与建议

### 问题 1: label_wide 无独立增量入口
- 当前必须重跑 neutralize 流程才能更新标签
- 建议: 抽取独立的 `run_label_pipeline()` 函数

### 问题 2: 数据更新链断裂
- API `/stocks/update` 只更新 daily_bar
- feature_wide 需要手动触发 `run_raw_feature_pipeline()`
- label_wide 需要手动触发 `run_neutralize_pipeline()`
- 建议: 提供一键更新入口，按依赖顺序自动执行

### 问题 3: cum_factor 定义不正确
- 当前是 `(1 + ret).cumprod()`，不是真实复权因子
- 只是累计收益链
- 建议: 要么改名 `cum_return_index`，要么引入真实复权因子

### 问题 4: 缺少自动化调度
- 各层更新需要手动触发
- 建议: 
  - 短期：提供统一的更新脚本
  - 长期：定时任务自动检测并增量更新

---

## 建议的统一更新流程

```python
def run_daily_update():
    """每日增量更新（建议实现）"""
    # 1. 更新 daily_bar
    from api.routes.stocks import _run_incremental_update
    _run_incremental_update(cfg)
    
    # 2. 更新 feature_wide
    from pipeline import run_raw_feature_pipeline
    run_raw_feature_pipeline(cfg)
    
    # 3. 更新 label_wide
    from pipeline import run_label_pipeline  # 需要抽取
    run_label_pipeline(cfg)
    
    # 4. (可选) 触发因子分析
    from pipeline import run_factor_analysis_pipeline
    run_factor_analysis_pipeline(cfg)
```

---

## 文件索引

| 模块 | 文件 | 职责 |
|------|------|------|
| API 入口 | `api/routes/stocks.py` | 触发增量下载 |
| ETL 入库 | `src/data_hub/etl_process.py` | 统一入库函数 |
| 数据下载 | `src/data_hub/baostock_client.py` | BaoStock 封装 |
| 特征计算 | `src/feature_engine.py` | 因子生成 |
| 标签生成 | `src/label_gen.py` | 标签计算 |
| 特征存储 | `src/data_layer/feature_store.py` | feature_wide 读写 |
| 标签存储 | `src/data_layer/label_store.py` | label_wide 读写 |
| 主流程 | `pipeline.py` | 全链路编排 |
