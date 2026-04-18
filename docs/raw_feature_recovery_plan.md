# Raw Feature Recovery Plan

## 目标

解决 RearMirror 当前最主要的阻塞点：原始特征矩阵生成卡死或极慢，导致后续中性化、回测、因子分析、实验管理都无法稳定使用。

这份文档面向后续工程师或大模型，目标不是泛泛建议，而是给出按优先级排序的修复路径、需要修改的函数、建议的验收标准。

## 已确认事实

### 1. 入口链路

- `run_experiment.py` 在 `--steps raw_feature` 或 `feature` 时进入 `pipeline.run_raw_feature_pipeline()`
- `pipeline.run_raw_feature_pipeline()` 再调用 `src.feature_engine.build_alpha158()`

### 2. 当前“增量更新”是伪增量

`pipeline.run_raw_feature_pipeline()` 虽然会读取既有 `raw_feature_output`，但仍然无条件执行一次完整的 `build_alpha158(cfg, ...)`。随后才通过 `old_max` 与新结果拼接。

这意味着：

- 只要进入 raw feature 步骤，就会重算全历史因子
- 旧缓存只是在最终拼接时参与，而不是在计算阶段减少工作量
- 对 2016-2026 的 A 股长面板，这几乎必然导致长时间 CPU 占用和较大的内存压力

### 3. 当前原始特征阶段默认算全因子库

`src.feature_engine.build_alpha158()` 使用 `registry.list_factors()`，即遍历所有已注册因子组，而不是仅使用 `features.active_factors`。

这意味着：

- 原始阶段会计算所有注册组
- `active_factors` 只在 `run_neutralize_pipeline()` 做筛选
- 即使某些组最终不会用于建模，也已经提前消耗了计算和 I/O

### 4. 主要热点在 rolling 与 technical 因子实现

以下类型的算子在全市场面板上成本很高：

- `groupby().transform(lambda x: x.rolling(d).apply(...))`
- `rolling(...).quantile(...)`
- 窗口内 `rank`
- 窗口内 `argmax/argmin`
- 窗口内 `MAD` 计算
- 同一窗口重复多次 `groupby(...).transform(...)`

重点文件：

- `src/factors/builtin_rolling.py`
- `src/factors/builtin_rolling_ext.py`
- `src/factors/builtin_technical.py`

其中最可能的重灾区包括：

- `feat_RANK{d}`
- `feat_IMAX{d}` / `feat_IMIN{d}`
- `feat_QTLU{d}` / `feat_QTLD{d}`
- `feat_CCI{d}` 中基于 `rolling.apply` 的 MAD
- `_calc_exact_ols()` 中的 `rolling.apply`

### 5. checkpoint 当前会放大内存与 I/O

`build_alpha158()` 每完成一个因子组就写一次 group parquet；恢复时再把每个组的结果 merge 回主 DataFrame。

这会带来两个副作用：

- 恢复阶段要做多次宽表 merge
- 中间 DataFrame 越来越宽，后续 groupby/rolling 会更吃内存

### 6. 当前“像卡死”不一定是真的死锁

更可能是以下情况之一：

- 某个窗口算子极慢，长时间没有日志
- Python 层 rolling.apply 导致单核热点
- 宽表 merge / parquet 序列化占用很久
- `gc.collect()` 在内层循环反复触发停顿

## 修复优先级

不要同时大改全部模块。按下面顺序推进，收益最大且可控。

### P0. 先修真实增量

目标：在没有新增交易日时，raw feature 步骤应快速退出；有新增交易日时，只为新增区间和必要窗口缓冲区计算。

建议改动：

1. 修改 `pipeline.run_raw_feature_pipeline()`
2. 增加 `build_alpha158()` 的数据切片参数，例如：
   - `input_df: pd.DataFrame | None = None`
   - 或 `date_range: tuple[pd.Timestamp, pd.Timestamp] | None = None`
3. 当已有旧缓存时：
   - 读取旧缓存最大日期 `old_max`
   - 计算 `warmup_start = old_max - max_window - safety_margin`
   - 从 CanonicalStore 只加载 `warmup_start` 之后的数据
   - 只对该片段计算因子
   - 最终仅保留 `date > old_max` 的新结果并追加到旧缓存

注意：

- `warmup_start` 必须向前多取至少 `max(windows)` 个交易日，否则 rolling 特征边界会错
- 如果配置指纹、因子代码哈希、窗口集合发生变化，应强制全量重算

伪代码：

```python
if cache_is_fresh and raw_output_exists:
    existing = read_raw_feature_cache()
    old_max = existing["date"].max()
    if old_max >= latest_trade_date:
        return existing, infer_features(existing), infer_group_map(existing)

    slice_start = trading_day_shift(old_max, -(max_window + 5))
    input_df = load_canonical_slice(start=slice_start)
    delta_df, all_features, group_map = build_alpha158(cfg, input_df=input_df)
    append_df = delta_df[delta_df["date"] > old_max]
    raw_df = concat_existing_and_append(existing, append_df)
else:
    raw_df, all_features, group_map = build_alpha158(cfg)
```

### P1. 把 raw feature 的计算范围改为“按需”

目标：默认只计算本次实验需要的因子组，不再无条件计算完整注册表。

建议改动：

1. 修改 `src.feature_engine.build_alpha158()`，新增参数：
   - `factor_groups: list[str] | None = None`
2. 若未显式传入，则读取：
   - `cfg["features"].get("active_factors")`
3. 仅在明确需要构建“全量因子资产库”时，才允许走 `registry.list_factors()`
4. 增加配置开关，例如：
   - `features.compute_all_registered_factors: false`

原因：

- 当前文档宣传的是“原始矩阵支持增量更新”，但如果每次仍算所有组，整体收益会被吞掉
- 真正的实验流程通常只关心当前 profile 中的因子组

### P2. 优化热点算子，先抓最慢的 20%

目标：在不重写整个因子系统的前提下，先砍掉最重的 Python-level rolling.apply。

建议顺序：

1. `builtin_technical.py`
   - 把 `delta`、`tp`、`vwap` 等可复用中间量移出窗口循环
   - `CCI` 的 MAD 若短期内无高效实现，可先提供开关将其作为 optional feature
2. `builtin_rolling.py`
   - 复用同一窗口的 rolling mean/std/max/min
   - `_calc_exact_ols()` 是典型热点，优先重写
   - `feat_RANK{d}` 不要继续用 `pd.Series(y).rank(...)` 的 Python lambda
3. `builtin_rolling_ext.py`
   - `QTLU/QTLD` 的 quantile 很慢，优先评估是否暂时下线或改为近似分位数
   - `CORD` 中多次 rolling mean/std 可以合并复用

实现策略建议：

- 能用 `rolling().mean/std/min/max/sum` 的，一律不用 `rolling.apply`
- 能先构造中间序列再统一按 `groupby(df["code"])` rolling 的，不要在每个因子里重复 groupby
- 对 `RANK/IMAX/IMIN/quantile/MAD/OLS` 这类难向量化的算子：
  - 优先考虑 `numba`
  - 或单独下沉为可选因子组
  - 或在 profiling 后先临时禁用最慢的少数因子，恢复主链路可用性

### P3. 收缩 checkpoint 与宽表写入策略

目标：避免“为了断点续传而把内存和 I/O 再放大一轮”。

建议改动：

1. checkpoint 不再恢复为“merge 回主宽表”
2. 每个因子组以独立窄表保存：
   - `code`
   - `date`
   - 该组 `feat_*`
3. 最终需要宽表时，只在落盘前做一次 assemble
4. 如果数据量继续扩大，可进一步按 code shard 切分：
   - 例如按股票代码哈希分为 `N` 个分片

### P4. 增强可观测性

目标：让“卡死”可以在日志中被明确归因。

至少增加以下日志：

- 每个因子组开始/结束时间
- 每个窗口 `d` 的耗时
- 当前处理行数、股票数、生成列数
- checkpoint 写盘耗时
- 当前进程 RSS 内存

建议日志样式：

```text
[raw_feature] group=rolling window=20 rows=3,200,000 cols=17 elapsed=28.4s rss=5.8GB
```

如果使用 `progress_cb`，不要只在组级别更新；窗口级别也要汇报。

## 推荐实施顺序

### 第一轮提交

目标：尽快让 raw feature 重新可用。

- 修复真实增量
- 增加按需因子组计算
- 增加窗口级耗时日志
- 暂时不做复杂并行

### 第二轮提交

目标：进一步把全量计算时间压下来。

- 逐个治理最慢因子
- 删除窗口内不必要的 `gc.collect()`
- 重构 checkpoint 为窄表/分片

### 第三轮提交

目标：做长期架构优化。

- 评估是否将更多 rolling 计算下沉到 DuckDB/Polars/Numba
- 评估是否取消原始阶段的单一超宽 Parquet，改为资产化分组存储

## 验收标准

至少满足以下条件，才算 raw feature 问题得到控制：

1. 无新增交易日时，再次执行 `raw_feature` 不应重算全量因子。
2. 有新增交易日时，只应重算窗口缓冲区加新增日期，而不是重算 2016-至今全历史。
3. 日志能明确看到每个组/窗口耗时，能够定位最慢因子。
4. `active_factors` 缩减后，原始阶段总耗时应显著下降。
5. 同一配置重复运行，产出文件和 feature 列集合应稳定一致。

## 建议的验证方式

先只跑 raw feature，不要一开始就串全链路：

```bash
python run_experiment.py configs/profiles/zz500_xgb_baseline.yaml --steps raw_feature
```

建议做三组验证：

1. 空缓存首次运行
   - 观察总耗时、单组耗时、峰值内存
2. 无新增数据再次运行
   - 应快速退出或仅做极轻量校验
3. 仅新增少量交易日
   - 应只重算增量区间，不应出现全历史滚动计算

如果需要先恢复最小可用链路，可临时缩小实验范围：

- 降低 `etl.max_stocks`
- 缩减 `features.windows`
- 暂时只保留 `kline`、`rolling`

但这些都只是调试/止血手段，不是最终修复。

## 不建议的做法

- 不要先给 raw feature 上多进程，再去面对全量重算和宽表 merge
- 不要只加日志而不修真实增量
- 不要在未 profiling 的情况下大面积重写所有因子
- 不要优先修改 Dashboard 或回测模块，它们不是当前主瓶颈

## 最小改动清单

如果只能做一次小步提交，优先改这些文件：

- `pipeline.py`
  - 修复真实增量逻辑
- `src/feature_engine.py`
  - 支持按需因子组
  - 增加输入切片/窗口级日志
- `src/factors/builtin_rolling.py`
  - 优先治理 `RANK` 和 OLS
- `src/factors/builtin_technical.py`
  - 优先治理 `CCI` 和重复 rolling

这样做完后，通常就足以让其他流程重新开始推进。