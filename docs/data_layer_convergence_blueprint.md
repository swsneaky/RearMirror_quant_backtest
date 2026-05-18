# Data Layer Convergence Blueprint

## 1. Scope

这份蓝图只解决一个问题：让 RearMirror 的 raw、canonical、feature、label、dataset 五层边界与日常主路径收敛到 [AI_CONTEXT.md](e:/quant/RearMirror/AI_CONTEXT.md) 的长期规则上。

本蓝图不处理具体性能调优、不修单条测试、不讨论策略效果。

## 2. Architecture Decisions

### 2.1 Raw Layer

- `stock_daily_cache/<code>.parquet` 是唯一 raw layer 主载体。
- raw layer 的职责是保真、追溯、重放、审计；它不是研究流程正式输入。
- raw layer 可以保留上游字段痕迹、下载元数据和不完全标准化列。
- 下游 feature、label、backtest、analysis 不得默认直接读取 raw cache。

### 2.2 Canonical Layer

- `daily_bar`、`industry_map`、`index_bar` 是研究流程唯一正式市场数据入口。
- 日常主路径必须是：
  1. 下载增量到 raw cache
  2. 规范化校验
  3. 按主键增量 upsert 到 `daily_bar`
- `etl.raw_output` 不再被定义为“研究正式输入”，只允许作为 canonical export / rebuild snapshot / 导入导出兜底文件。
- canonical 入库失败、主键异常、关键字段异常必须阻断主流程，不允许 `warning` 后继续下游。

### 2.3 Feature Layer

- 原始特征矩阵属于 feature layer 的 staging/cache 子层，不属于 canonical layer。
- 正式特征资产是版本化 `feature_set`，其物化表为 `feat__{hash}`。
- `feature_wide` 仅是兼容别名，不再视为长期正式入口。
- 正式下游消费者应优先通过 `feature_set_id` 读取版本化表。

### 2.4 Label Layer

- 正式标签资产是版本化 `label_set`，其物化表为 `label__{hash}`。
- `label_wide` 仅是兼容别名，不再视为长期正式入口。
- 正式下游消费者应优先通过 `label_set_id` 读取版本化表。

### 2.5 Dataset Layer

- DatasetBuilder 是 feature/label/canonical 的唯一拼装入口。
- 数据集构建前必须执行 feature_set 与 label_set 的配对校验。
- 训练、回测、IC 分析都只消费：
  - `feature_set_id`
  - `label_set_id`
  - canonical `daily_bar`

## 3. File Role Clarification

### 3.1 `etl.raw_output`

当前命名容易造成“raw_output 是 raw layer 正式文件”的误解。架构上应改为以下语义：

- 推荐新语义名：`canonical_snapshot_output` 或 `daily_bar_export`
- 短期兼容阶段允许继续使用 `etl.raw_output` 这个配置名
- 但文档与代码注释必须统一说明：
  - 它是 canonical 层的导出/快照文件
  - 不是 raw layer 主载体
  - 不是研究流程默认真源

### 3.2 Fallback Parquet

- fallback parquet 的使用场景只允许是：
  - 导入导出
  - 灾难恢复
  - 历史修复
  - 无数据库环境下的离线调试工具
- 正常研究主路径不应依赖“SQLite 不可用就自动回退 parquet 继续跑”。

## 4. Failure Semantics

### 4.1 ETL / Canonical

- `merge_and_clean()` 不应再以“全量拼接 cache -> 落 parquet -> 尝试写 DB”为日常主路径。
- Canonical 入库必须拆成显式阶段：
  - raw cache scan
  - normalize/validate
  - incremental upsert to `daily_bar`
- 任一阶段失败时，主流程中断并抛出异常。

### 4.2 CanonicalStore

- `CanonicalStore` 应新增严格模式，建议接口：

```python
CanonicalStore.from_config(cfg, require_db: bool = True)
```

- 研究主流程默认 `require_db=True`
- 只有重建工具、导出工具、离线调试工具才允许 `require_db=False`
- 当 `require_db=True` 且 `daily_bar` 不可用时，必须报错，不得默默回退 parquet

## 5. Feature / Label Pairing Contract Implementation

Session B 需要在 DatasetBuilder 中新增显式校验接口，建议如下：

```python
def validate_feature_label_pair(
    self,
    feature_set_id: str,
    label_set_id: str,
    *,
    max_missing_ratio: float = 0.0,
    sample_report_limit: int = 20,
) -> dict:
    ...
```

最少输出以下统计：

- `feature_rows`
- `label_rows`
- `intersection_rows`
- `feature_only_rows`
- `label_only_rows`
- `feature_date_range`
- `label_date_range`

校验规则：

- 默认严格模式下，只要存在无法由 warmup、horizon、停牌、过滤规则解释的差异，就报错阻断。
- 若项目需要保留容忍区间，必须通过显式配置控制，而不是默认放行。
- 校验报告必须在训练集构建前输出，不能等回测结果异常后再倒查。

## 6. Migration Order

### Phase 1: Canonical 主路径收敛

- 改 `src/data_hub/etl_process.py`
- 把日常主路径改成增量 upsert `daily_bar`
- 将 DB 写失败从 `warning` 改为阻断异常
- 保留 parquet 导出，但降级为副产物

### Phase 2: Canonical 读取门禁

- 改 `src/data_layer/canonical.py`
- 为研究主流程引入 `require_db=True`
- 只给导出/恢复/离线工具保留 parquet fallback

### Phase 3: Feature/Label 正式入口收敛

- 改 `src/data_layer/feature_store.py`
- 改 `src/data_layer/label_store.py`
- 明确 `feature_wide` / `label_wide` 是兼容别名
- pipeline / backtest / ic_analysis 优先消费 `feature_set_id` / `label_set_id`

### Phase 4: Dataset 配对校验落地

- 改 `src/data_layer/dataset_builder.py`
- 在 build_train_dataset / build_analysis_dataset 前执行 pair validation
- 报告交集、左独有、右独有统计并根据规则阻断

### Phase 5: Legacy Parquet 退役

- 保留导出用途
- Dashboard 与主流程移除对 legacy merged parquet 的默认依赖
- 完成后再讨论删除兼容写路径

## 7. Non-Goals

- 不在本轮处理 raw feature 性能优化
- 不在本轮改动 cross_section 逻辑
- 不在本轮直接删除所有 parquet
- 不在本轮重写 Dashboard 外观或任务系统

## 8. Expected Deliverables For Session B

Session B 完成后，至少要满足以下结果：

1. 研究主流程默认在 canonical DB 不可用时直接失败，而不是静默回退。
2. ETL 日常路径以增量 upsert `daily_bar` 为主，parquet 仅为导出副产物。
3. DatasetBuilder 在拼装前输出 feature/label 配对报告，并在不合规时阻断。
4. pipeline/backtest/analysis 对正式版本化资产的依赖清晰可追踪。
5. `feature_wide` / `label_wide` / legacy parquet 的兼容身份在代码注释与日志里表述一致。