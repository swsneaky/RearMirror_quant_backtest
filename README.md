# RearMirror

## 发布说明

本项目当前发布物为 **本地研究版源码包（Research Release）**，适用于具备 Python/前端基础的技术用户。

请注意：
- 发布包 **不包含** `data/quant.db`
- 发布包 **不包含** 大体积原始行情与特征缓存
- 用户需要自行生成数据库，或单独获取已有数据库快照
- 因此该发布包不是"解压即用"的完整离线包，而是"源码 + 配置 + 文档 + 前端构建产物"的技术发布包

---

A 股多因子量化研究平台 — Alpha158 因子体系 · 截面中性化 · 树模型选股 · Walk-Forward 回测 · SQLite 数据中台

---

## 一句话定位

用**一个 YAML** 定义实验、用**一条命令**跑通全链路、所有中间产物和实验血缘**自动入库**，在 A 股中证 500 / 沪深 300 上做截面多因子研究。

## 迭代循环

```
原始特征工程 (全量因子) → 因子粗筛 → 截面中性化 → 模型训练 + 回测
                                                        ↓
                          因子精筛 (IC/ICIR/SHAP) ←── 回测结果
                                ↓
                         调整因子组合, 开始下一轮迭代
```

- **原始特征工程**与**中性化**拆分为独立步骤
- 原始特征矩阵支持**增量更新**, 避免重复计算
- 每次中性化按因子组合版本化, 同一组合 → 同一 asset_id

## 目录

- [快速开始](#快速开始)
- [三种使用方式](#三种使用方式)
- [架构总览](#架构总览)
- [SQLite 数据中台](#sqlite-数据中台)
- [因子体系](#因子体系)
- [模型与回测](#模型与回测)
- [因子分析](#因子分析)
- [实验管理](#实验管理)
- [Dashboard](#dashboard)
- [扩展自定义因子](#扩展自定义因子)
- [配置参考](#配置参考)
- [Docker 部署](#docker-部署)
- [设计原则](#设计原则)

---

## 快速开始

```bash
# 0. 安装 (Python ≥ 3.10)
cd RearMirror
pip install -e .          # editable install，解决所有 import
pip install -r requirements.txt

# 1. 全链路一键运行 (下载 → ETL → 原始特征 → 中性化 → 回测 → 因子分析)
python pipeline.py

# 2. 或者启动前端可视化界面
cd frontend && npm run dev
```

> **首次运行**需下载中证 500 成份股十年日线数据，约 500 只股票，耗时取决于网络。后续运行会命中缓存。

### 最小可用三步

```bash
# Step 1 — 数据下载 + ETL
python -c "
from src.config_loader import load_config
from src.data_hub import run_downloader, merge_and_clean
cfg = load_config()
run_downloader(cfg)
merge_and_clean(cfg)
"

# Step 2 — 原始特征 → 中性化 → 回测
python -c "
from pipeline import run_raw_feature_pipeline, run_neutralize_pipeline, run_backtest_pipeline
raw_df, feats, gfm = run_raw_feature_pipeline()     # 全量因子, 增量更新
_, asset_ids = run_neutralize_pipeline(raw_df=raw_df, all_features=feats, group_feature_map=gfm)
results, metrics = run_backtest_pipeline(
    feature_set_id=asset_ids.get('feature_set_id'),
    label_set_id=asset_ids.get('label_set_id'),
)
print(f'年化收益: {metrics[\"ann_return\"]*100:.2f}%')
print(f'夏普比率: {metrics[\"sharpe_ratio\"]:.2f}')
"

# Step 3 — 查看结果
# 启动前端查看回测结果
cd frontend && npm run dev
```

---

## 三种使用方式

### 方式一：CLI 提交任务

```bash
# 基线回测
python task_cli.py submit --model xgboost --top-k 30

# 用 profile 覆盖参数
python task_cli.py submit --profile configs/profiles/zz500_xgb_depth6_topk50.yaml

# 启动后台执行器
python task_cli.py worker

# 查看任务列表
python task_cli.py list
```

### 方式二：Profile 实验管理

```bash
# 一个 profile = 一组实验参数，只写要覆盖 base_config 的项
python run_experiment.py configs/profiles/zz500_xgb_baseline.yaml
python run_experiment.py configs/profiles/hs300_lgbm_depth6.yaml --steps raw_feature,neutralize,backtest
```

Profile 示例 (`configs/profiles/zz500_xgb_baseline.yaml`)：

```yaml
etl:
  index_name: "zz500"
model:
  active: "xgboost"
  xgboost:
    n_estimators: 100
    max_depth: 4
backtest:
  top_k: 30
```

### 方式三：前端可视化界面

```bash
cd frontend && npm run dev
```

交互式配置 → 一键提交 → 实时看板。

---

## 架构总览

```
RearMirror/
├── configs/
│   ├── base_config.yaml              # 全局配置 (唯一真理来源)
│   └── profiles/                     # 实验参数覆盖文件
├── pipeline.py                       # 主编排器 (raw_feature → neutralize → backtest)
├── run_experiment.py                 # Profile 实验启动器
├── task_cli.py                       # CLI 任务管理
├── src/
│   ├── config_loader.py              # YAML 配置加载 + Profile 合并
│   ├── registry.py                   # 插件注册表 (因子 FactorMeta + 模型)
│   ├── feature_engine.py             # 特征工厂 (Registry 驱动)
│   ├── cross_section.py              # 截面中性化 (MAD + 行业中性 + Z-Score)
│   ├── label_gen.py                  # 标签生成
│   ├── experiment_store.py           # 实验结果 + 血缘落盘
│   ├── storage_manager.py            # 存储管理 & 缓存指纹
│   ├── data_hub/                     # 数据下载与 ETL
│   │   ├── baostock_client.py        #   BaoStock 日线 + 成份股
│   │   ├── akshare_client.py         #   AkShare 行业映射
│   │   └── etl_process.py            #   合并清洗 → SQLite + Parquet
│   ├── data_layer/                   # 数据资产层
│   │   ├── db.py                     #   SQLite 连接 (WAL) + 14 张表 Schema
│   │   ├── asset_id.py               #   确定性资产 ID 生成
│   │   ├── canonical.py              #   Canonical 数据 (ETL 只读封装)
│   │   ├── feature_store.py          #   FeatureStore (版本化 feat_ 因子)
│   │   ├── label_store.py            #   LabelStore (版本化 label_ 标签)
│   │   └── dataset_builder.py        #   DatasetBuilder (SQL JOIN 拼装)
│   ├── factors/                      # 因子库 (6 组 ~150 个因子)
│   │   ├── builtin_kline.py          #   K 线形态 (7)
│   │   ├── builtin_rolling.py        #   滚动统计 (17×5)
│   │   ├── builtin_rolling_ext.py    #   扩展统计 (12×5)
│   │   ├── builtin_technical.py      #   技术指标 (23)
│   │   ├── builtin_turnover.py       #   换手率 (11)
│   │   ├── builtin_valuation.py      #   估值 (44)
│   │   └── ic_analysis.py            #   IC / ICIR / Decay 分析
│   ├── models/
│   │   └── builtin_models.py         #   LightGBM / XGBoost / RandomForest
│   ├── ml_core/
│   │   └── backtest.py               #   Walk-Forward 滚动回测引擎
│   └── tasking/                      # 异步任务系统
│       ├── manager.py                #   任务提交 & 调度
│       ├── executor.py               #   多进程执行器
│       ├── runner.py                 #   子进程运行器
│       └── store.py                  #   任务状态持久化
├── Dockerfile + docker-compose.yml
└── data/
    ├── quant.db                      # SQLite 统一数据库 (WAL 模式, 支持并发)
    ├── stock_daily_cache/            # 个股日线缓存
    ├── raw/                          # ETL canonical 数据
    ├── features/                     # Parquet 兼容副本
    │   ├── *_raw.parquet             #   原始全因子矩阵 (增量更新)
    │   └── *_neutralized.parquet     #   中性化矩阵 (版本化)
    └── results/                      # 实验产物
```

### 数据流

```
BaoStock / AkShare
     │
     ▼
stock_daily_cache/              个股日线 Parquet 缓存
     │
     ▼
SQLite daily_bar ◄──── ETL     Canonical 宽表 (raw_* 列)
     │
     ├──▶ build_alpha158()      全量因子裂变 (原始值, 未中性化)
     │       ↓
     │    raw_feature.parquet   原始特征矩阵 (支持增量更新)
     │       ↓
     ├──▶ 因子粗筛              active_factors + excluded_features
     │       ↓
     ├──▶ cross_section         MAD + 行业中性化 + Z-Score (仅选用因子)
     │       ↓
     ├──▶ FeatureStore          feat__{hash} 版本化中性化矩阵
     ├──▶ LabelStore            label__{hash} 版本化标签矩阵
     │       ↕ asset_registry    资产目录 + 因子定义
     ▼
DatasetBuilder                  SQL JOIN → 训练集 / 分析集
     │
     ├──▶ Walk-Forward          滚动训练 + 预测
     │       ↓
     │    ExperimentStore       predictions / holdings / nav / metrics
     │       ↓                  experiment_run 血缘记录
     │
     ├──▶ IC Analysis           因子有效性 → factor_analysis_summary
     │                                ↓
     │                          因子精筛 → 调整因子组合 → 下一轮迭代
     ▼
前端 Dashboard                  SQLite 优先读取 → Parquet 兜底
```

---

## SQLite 数据中台

所有数据资产以 **SQLite** (`data/quant.db`, WAL 模式) 为主存储，Parquet 作为冷备和兼容 fallback。
SQLite WAL 模式允许 Dashboard（读）和 Task Worker（写）同时访问同一数据库，不再有文件独占锁问题。

### 表清单

| 表名 | 用途 | 主键 |
|------|------|------|
| `daily_bar` | ETL canonical 日线 | date, code |
| `industry_map` | 行业映射 | code |
| `index_bar` | 指数行情 | date, code |
| `feature_wide` | 最新中性化因子矩阵 (兼容别名) | date, code |
| `label_wide` | 最新标签矩阵 (兼容别名) | date, code |
| `feat__{hash}` | 版本化因子矩阵 | date, code |
| `label__{hash}` | 版本化标签矩阵 | date, code |
| `asset_registry` | 数据资产目录 | asset_id |
| `factor_definitions` | 因子代码身份 + 输入输出 | factor_id |
| `feature_set_factors` | 因子集组成关系 | (feature_set_id, factor_id) |
| `experiment_run` | 实验血缘 (关联特征集/标签集/模型) | experiment_id |
| `predictions` | 预测结果 | (experiment_id, date, code) |
| `holdings` | 持仓快照 | (experiment_id, date, code) |
| `nav_daily` | 净值曲线 | (experiment_id, date) |
| `metrics_summary` | 绩效汇总 | experiment_id |
| `factor_analysis_summary` | IC/ICIR 汇总 | (analysis_id, factor_name) |
| `factor_ic_series` | IC 时间序列 | (analysis_id, date, factor_name) |

### 版本化资产协议

每次 `run_neutralize_pipeline()` 根据因子组合自动计算 SHA-256 哈希：

```
feature_config = { selected_features (排序), windows, cross_section }
asset_id = "feature_set__{hash[:12]}"          # e.g. feature_set__a3b9c7d2e1f0
table    = "feat__{hash[:12]}"                 # SQLite 表名
```

- 同一因子组合永远生成**同一** asset_id（幂等）
- 不同因子组合自动创建新版本
- 原始特征矩阵独立于版本化体系，通过缓存指纹实现增量更新

---

## 因子体系

基于 Alpha158 框架，6 组因子共约 **150 个**截面标准化后的因子：

| 因子组 | 基础因子 | 窗口展开 | 合计 | 说明 |
|--------|---------|---------|------|------|
| `kline` | 7 | — | 7 | KMID, KLEN, KUP/KLOW 等日内形态 |
| `rolling` | 17 | ×5 | 85 | ROC, MA, STD, RSV, BETA 等滚动统计 |
| `rolling_ext` | 12 | ×5 | 60 | QTLU/D, CNTP/N/D, SUMP/N/D 等 |
| `technical` | — | 3×5 + 8 | 23 | RSI, CCI, MACD, KDJ, OBV, MFI |
| `turnover` | — | 2×5 + 1 | 11 | 换手率均值/波动/变化 |
| `valuation` | — | 4×(2×5+1) | 44 | PE/PB/PS/PCF 的 MA/RANK/LOG |

**窗口**：`[5, 10, 20, 30, 60]`（交易日）

每个因子均声明 `FactorMeta`（输入列、输出列、是否窗口化），写入 `factor_definitions` 表。

### 原始 vs 中性化

| 步骤 | 产物 | 路径 | 增量 | 版本化 |
|------|------|------|------|--------|
| `run_raw_feature_pipeline` | 原始因子矩阵 | `raw_feature_output` | ✅ 支持 | ❌ 单份 |
| `run_neutralize_pipeline` | 中性化矩阵 | `features.output` / FeatureStore | ❌ | ✅ 按组合hash |

原始矩阵包含**全部**注册因子的未经截面处理的原始值。
中性化矩阵仅包含**选用**因子经 MAD + 行业中性化 + Z-Score 后的标准化值。

### 截面中性化

每个交易日独立执行三步处理：

1. **MAD 去极值**：中位数 ± 3.148× 中位数绝对偏差
2. **行业中性化**：减去行业均值 (样本 < 5 则跳过)
3. **Z-Score 标准化**：零均值、单位方差

---

## 模型与回测

### 支持模型

在 `configs/base_config.yaml` 中切换：

```yaml
model:
  active: "xgboost"   # lightgbm | xgboost | random_forest
```

三个模型的超参数均在同一文件中配置，Dashboard/CLI 可动态覆盖。

### Walk-Forward 回测引擎

```
┌────────────┐                ┌────────────┐
│ Train 500d │── gap 5d ──▶   │ Predict 5d │ ──▶ 选股 Top K ──▶ 净值计算
└────────────┘                └────────────┘
                     ↓ 滚动 5d
┌────────────┐                ┌────────────┐
│ Train 500d │── gap 5d ──▶   │ Predict 5d │ ──▶ ...
└────────────┘                └────────────┘
```

- **训练窗口** 500 天 · **隔离带** 5 天（≥ label horizon，防前瞻偏差）
- **每期选** Top K 只，等权持仓
- **摩擦成本** 万四 / 涨跌停过滤 / 换手率约束
- 每个折叠保存模型 + 训练元信息 (特征重要性 Top 20)

### SHAP 因子重要性

```yaml
backtest:
  return_shap: true   # 每个折叠计算 TreeSHAP
```

---

## 因子分析

```bash
python -c "
from pipeline import run_factor_analysis
out = run_factor_analysis()
print(out['summary'].head(10))   # ICIR Top 10
"
```

| 分析项 | 说明 | 数据库表 | Parquet 兜底 |
|--------|------|-----------|-------------|
| IC 时间序列 | 每日截面 Spearman IC | `factor_ic_series` | `ic_series.parquet` |
| ICIR 排行 | IC 均值 / 标准差 / ICIR / 正占比 | `factor_analysis_summary` | `icir.parquet` |
| IC Decay | lag 1..10 的 IC 衰减 | — | `ic_decay.parquet` |
| SHAP 重要性 | TreeSHAP 均值绝对值 | — | `shap_importance.parquet` |

IC 分析会自动通过 `DatasetBuilder` 从 SQLite 读取数据，不再依赖 Parquet 中间文件。

---

## 实验管理

### 实验血缘

每次回测自动在 `experiment_run` 表中记录完整血缘：

| 字段 | 说明 |
|------|------|
| `experiment_id` | 唯一实验标识 |
| `feature_set_id` | 使用的因子集版本 → `asset_registry` |
| `label_set_id` | 使用的标签集版本 → `asset_registry` |
| `model_name` | 模型名称 |
| `model_params_hash` | 超参数哈希 |
| `config_snapshot` | 完整配置 JSON 快照 |
| `status` | running → done / failed / empty |
| `created_at` / `finished_at` | 时间戳 |

通过 `feature_set_id` 可追溯到具体使用了哪些因子组、哪些窗口、什么截面处理参数。

### 实验产物

每个实验目录下：

```
experiments/tasks/task_{id}/
├── config_snapshot.yaml       # 完整配置快照
├── features/                  # 因子分析结果
├── models/
│   ├── model_fold_*.pkl       # 每折模型
│   └── train_meta_*.json      # 训练元信息 (样本量/特征重要性)
├── results/
│   ├── predictions.parquet
│   ├── holdings.parquet
│   ├── nav_daily.parquet
│   └── metrics_summary.json
└── logs/
    └── runtime.log
```

同时数据库中 `predictions` / `holdings` / `nav_daily` / `metrics_summary` 表也会有对应记录（按 `experiment_id` 分区），支持跨实验 SQL 查询。

---

## Dashboard

前端可视化界面提供完整的研究工作台：

```bash
cd frontend && npm run dev
```

**主要页面**：
- Dashboard：研究概览
- Data Layers：数据层监控
- Backtest：回测工作台
- HPO：超参优化监控
- Factors：因子研究
- Stocks：股票数据看板

---

## 扩展自定义因子

在 `src/factors/` 下新建 `.py` 文件：

```python
from src.registry import registry, FactorMeta

@registry.register_factor("my_factor", meta=FactorMeta(
    group="my_factor",
    input_cols=["raw_close", "raw_open"],
    output_cols=["MY_RATIO"],
    description="开盘收盘比",
    windowed=False,
))
def my_factor(df, grouped, windows, f32):
    df["feat_MY_RATIO"] = (df["raw_close"] / df["raw_open"]).astype(f32)
    return df, ["feat_MY_RATIO"]
```

然后在 `configs/base_config.yaml` 中激活：

```yaml
features:
  active_factors: [kline, rolling, my_factor]
```

因子的 `FactorMeta` 会自动注册到 `factor_definitions` 表，包括代码哈希（通过 `inspect.getsource` 计算）。配置变更会自动生成新的 `feature_set` 版本。

---

## 配置参考

所有参数收口于 `configs/base_config.yaml`，Profile 文件只需写要覆盖的项。

### 核心配置区段

| 区段 | 关键参数 | 说明 |
|------|---------|------|
| `database` | `path` | SQLite 数据库路径 |
| `etl` | `index_name`, `start_date`, `end_date`, `max_stocks` | 数据源 |
| `features` | `active_factors`, `excluded_features`, `windows`, `raw_feature_output` | 因子工程 |
| `cross_section` | `mad_multiplier`, `min_industry_stocks` | 截面处理 |
| `label` | `name`, `horizon`, `method` | 标签定义 |
| `model` | `active`, `lightgbm.*`, `xgboost.*`, `random_forest.*` | 模型 |
| `backtest` | `train_window`, `gap`, `test_step`, `top_k`, `friction_cost` | 回测引擎 |

### 快速调参示例

```python
from src.config_loader import load_config
from pipeline import run_raw_feature_pipeline, run_neutralize_pipeline, run_backtest_pipeline

cfg = load_config()
cfg["model"]["active"] = "lightgbm"
cfg["backtest"]["top_k"] = 50
cfg["backtest"]["return_shap"] = True

# 原始特征只算一次, 后续迭代只需重新中性化
raw_df, feats, gfm = run_raw_feature_pipeline(cfg)

# 不同因子组合 → 不同中性化版本
cfg["features"]["excluded_features"] = ["feat_KLOW2", "feat_KUP2"]
_, asset_ids = run_neutralize_pipeline(cfg, raw_df, feats, gfm)

results, metrics = run_backtest_pipeline(
    cfg,
    feature_set_id=asset_ids.get("feature_set_id"),
    label_set_id=asset_ids.get("label_set_id"),
)
```

---

## Docker 部署

```bash
docker-compose up pipeline     # 全链路：下载 → ETL → 特征 → 回测
docker-compose up api          # FastAPI 后端
```

数据通过 Volume 外挂 (`./data:/app/data`)，代码打入镜像。

---

## 设计原则

| # | 原则 | 实现 |
|---|------|------|
| 1 | **Config 唯一真理** | 所有超参收口于 `base_config.yaml`，Profile 做增量覆盖 |
| 2 | **列名前缀协议** | `raw_` / `feat_` / `label_` / `pred_`，一眼区分列含义 |
| 3 | **SQLite 主存储** | WAL 模式支持并发，14+ 张表统一管理，Parquet 降级为冷备 |
| 4 | **版本化资产** | 配置哈希 → 确定性 asset_id，同配置幂等 |
| 5 | **实验可追溯** | `experiment_run` 记录完整血缘链路 |
| 6 | **反未来穿越** | GAP ≥ label horizon，步长对齐预测周期 |
| 7 | **截面三步标准化** | MAD → 行业中性化 (小样本保护) → Z-Score |
| 8 | **插拔式模型** | Registry 装饰器注册，`.fit()/.predict()` 标准接口 |
| 9 | **插拔式因子** | `FactorMeta` 声明输入输出，配置激活，代码哈希追踪 |
| 10 | **Docker 容器化** | 数据 Volume 外挂，环境一键复现 |

---

## 依赖

- Python ≥ 3.10
- pandas, numpy, pyarrow
- lightgbm, xgboost, scikit-learn
- baostock, akshare (A 股数据源)
- fastapi, uvicorn (API 服务)
- shap (可选，因子重要性)

```bash
pip install -e .
pip install -r requirements.txt
```

## 扩展自定义模型

```python
from src.registry import registry

@registry.register_model("catboost")
class CatBoostWrapper:
    def __init__(self, **params): ...
    def fit(self, X, y): ...
    def predict(self, X): ...
```

## 数据格式

所有数据统一使用 **Parquet** 格式存储 (铁律三)，不使用 CSV/PKL。

## License

MIT
