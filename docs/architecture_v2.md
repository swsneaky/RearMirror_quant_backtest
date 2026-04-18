# RearMirror 架构升级方案 v2 — 数据驱动研究平台

## 一、设计目标

从脚本流水线升级为**版本化数据资产驱动**的研究平台:
- 每个数据资产 (raw, feature_set, label_set, model, experiment) 有唯一 ID 和版本
- 多版本共存: 不同因子集、不同标签、不同模型参数的实验互不覆盖
- 完整血缘: 任何实验可追溯到精确的数据版本 + 因子版本 + 配置快照
- SQLite 为唯一主存储, Parquet 降级为冷备份

## 二、版本协议

### 2.1 Asset ID 生成规则

```
asset_id = "{asset_type}__{sha256(config_payload)[:12]}"
```

- `config_payload` = 该资产类型专属的配置字典, 经 `json.dumps(sort_keys=True)` 序列化
- 同配置产出的资产 ID 幂等 (可重跑不产生新版本)
- 不同配置自动产生不同 ID (多版本共存)

### 2.2 物化表命名

| 资产类型        | SQLite 表名              | 示例                          |
|----------------|--------------------------|-------------------------------|
| feature_set    | `feat__{hash[:12]}`      | `feat__a1b2c3d4e5f6`         |
| label_set      | `label__{hash[:12]}`     | `label__x9y8z7w6v5u4`        |
| 其余 (固定表)  | 原表名不变                | `daily_bar`, `predictions` 等 |

### 2.3 兼容过渡

- `feature_wide` / `label_wide` 表保留为**默认别名**, 指向最新活跃版本
- 旧代码路径 (DatasetBuilder/Dashboard 读 `feature_wide`) 不感知变化
- 新代码路径可指定 `asset_id` 精确读取特定版本

## 三、SQLite Schema (新增表)

### 3.1 asset_registry — 中央资产目录

```sql
CREATE TABLE IF NOT EXISTS asset_registry (
    asset_id     VARCHAR PRIMARY KEY,
    asset_type   VARCHAR NOT NULL,   -- raw_data | feature_set | label_set | model | experiment | factor_analysis
    name         VARCHAR NOT NULL,   -- 人类可读名: 'zz500_alpha158'
    version      VARCHAR NOT NULL,   -- 时间戳版本号
    config_hash  VARCHAR NOT NULL,   -- SHA256 of config section
    parent_ids   VARCHAR,            -- JSON array of parent asset_ids (血缘)
    status       VARCHAR DEFAULT 'active',  -- active | archived | failed
    table_name   VARCHAR,            -- 物化表名 (feature_set/label_set 有此字段)
    row_count    INTEGER,
    col_count    INTEGER,
    created_at   TIMESTAMP DEFAULT current_timestamp,
    meta_json    VARCHAR,            -- 扩展元数据 (JSON)
    UNIQUE(asset_type, config_hash)
);
```

### 3.2 factor_definitions — 因子库版本目录

```sql
CREATE TABLE IF NOT EXISTS factor_definitions (
    factor_id     VARCHAR PRIMARY KEY,   -- 'kline__abc123'
    factor_group  VARCHAR NOT NULL,      -- 'kline' | 'rolling' | 'technical' ...
    code_hash     VARCHAR NOT NULL,      -- SHA256 of factor function source
    input_cols    VARCHAR NOT NULL,      -- JSON: ["raw_open","raw_close",...]
    output_cols   VARCHAR NOT NULL,      -- JSON: ["feat_KMID","feat_KLEN",...]
    windows       VARCHAR,               -- JSON: [5,10,20,30,60] or null
    description   VARCHAR,
    created_at    TIMESTAMP DEFAULT current_timestamp,
    UNIQUE(factor_group, code_hash)
);
```

### 3.3 feature_set_factors — 因子集组成

```sql
CREATE TABLE IF NOT EXISTS feature_set_factors (
    feature_set_id  VARCHAR NOT NULL,    -- FK → asset_registry.asset_id
    factor_id       VARCHAR NOT NULL,    -- FK → factor_definitions.factor_id
    PRIMARY KEY (feature_set_id, factor_id)
);
```

## 四、Registry 升级

### 4.1 FactorMeta 声明

```python
@dataclass
class FactorMeta:
    group: str               # 'kline', 'rolling', ...
    input_cols: list[str]    # 所需原始列
    output_cols: list[str]   # 产出因子列 (或生成函数)
    description: str = ""
```

### 4.2 注册方式

```python
@registry.register_factor("kline", meta=FactorMeta(
    group="kline",
    input_cols=["raw_open", "raw_high", "raw_low", "raw_close"],
    output_cols=["feat_KMID", "feat_KLEN", "feat_KUP", "feat_KLOW",
                 "feat_KMID2", "feat_KUP2", "feat_KLOW2"],
))
def compute_kline(df, grouped, windows, f32):
    ...
```

- code_hash 由 registry 自动计算 (inspect.getsource → SHA256)
- factor_id = `{group}__{code_hash[:12]}`

## 五、数据流 (升级后)

```
ETL           →  CanonicalStore (daily_bar)
                      ↓
              FeatureEngine.build()
              (读 CanonicalStore, 不读 raw parquet)
                      ↓
              FeatureStore.save(asset_id)
              → SQLite feat__{hash} 表
              → asset_registry 登记
              → feature_set_factors 登记
                      ↓
              DatasetBuilder.build(feature_set_id, label_set_id)
              → SQL JOIN feat__{hash} + label__{hash} + daily_bar
                      ↓
              run_walk_forward → ExperimentStore
              → asset_registry 登记 (parent_ids = [feat_id, label_id, model_id])
                      ↓
              Dashboard 读 asset_registry + 结果表
```

## 六、迁移计划

### Phase A — 元数据基础设施
- [ ] 新建 `src/data_layer/asset_id.py`: `make_asset_id()`, `make_config_hash()`
- [ ] `db.py`: 在 `_init_schema()` 中新增 3 张元数据表
- [ ] `registry.py`: 添加 `FactorMeta`, 升级 `register_factor` 签名
- [ ] 保持旧表不删，零破坏

### Phase B — 因子声明
- [ ] 6 个 builtin_*.py: 添加 `FactorMeta` 声明
- [ ] `feature_engine.py`: 从 CanonicalStore 读数据, 不再直接读 parquet
- [ ] `feature_engine.py`: 从 registry 获取 input_cols, 消除硬编码 `factor_required_raw`

### Phase C — 版本化 FeatureStore / LabelStore
- [ ] `FeatureStore.save()`: 写入 `feat__{hash}` 表 + `asset_registry` 登记
- [ ] `FeatureStore.save()`: 同时更新 `feature_wide` 别名 (兼容)
- [ ] `LabelStore.save()`: 同理
- [ ] `DatasetBuilder`: 支持 `asset_id` 参数精确定位版本

### Phase D — 血缘追踪
- [ ] `ExperimentStore`: 记录 parent_ids (feature_set_id, label_set_id)
- [ ] `pipeline.py`: 传递 asset_id 链路
- [ ] `ic_analysis.py`: 通过 DatasetBuilder 获取数据

### Phase E — Dashboard 迁移
- [ ] React 前端: 读 SQLite 结果表, 不读 parquet
- [ ] 资产浏览器: 列出 asset_registry, 支持版本对比

### Phase F — 清理
- [ ] 移除 legacy merged parquet 产出
- [ ] 移除 Parquet fallback 读取路径
- [ ] `data_versions` 表迁移到 `asset_registry`
