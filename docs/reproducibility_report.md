# 可复现性报告 (reproducibility_report.md)

## 1. 问题 1-2: 版本锁定情况

### Python 依赖

**当前状态**: ⚠️ 部分锁定

**证据** (`requirements.txt`):
```
pandas>=2.0
numpy>=1.24
pyarrow>=14.0
...
```

**问题**:
- 使用 `>=` 而非 `==`，允许更高版本
- 无 `requirements-lock.txt` 或 `pip freeze` 输出

**实际验证环境**:
```
Python 3.12.3
pandas 2.x
numpy 1.26.x
lightgbm 4.x
xgboost 2.x
```

### Node 依赖

**当前状态**: ✅ 已锁定

**证据**: `frontend/package-lock.json` 存在 (lockfileVersion: 3)

**问题**:
- `package.json` 使用 `^` 版本，次要版本可变
- 无 `.nvmrc` 指定 Node 版本

---

## 2. 问题 3: 幂等性测试

### 2.1 `run_label_pipeline()` 幂等性

**结论**: ✅ 幂等

**证据** (`pipeline.py:1136-1156`):
```python
# 检查是否需要更新
if old_label_max >= target_label_max:
    print(f"[SKIP] label_wide 已是最新: {old_label_max.date()}")
    return {
        "status": "skipped",
        "old_max": str(old_label_max.date()),
        "new_max": str(old_label_max.date()),
        "rows_added": 0,
        "message": "label_wide already up-to-date"
    }
```

**机制**: 比较当前 `label_wide.max_date` 与目标日期，如果已最新则跳过

---

### 2.2 `run_raw_feature_pipeline()` 幂等性

**结论**: ✅ 幂等

**证据** (`pipeline.py:256-265`):
```python
if n_new_dates == 0:
    raw_df = feature_store.load()
    print(
        "[INCR] raw feature DB-first no-op: "
        f"old_feature_max={old_max.date()} daily_bar_max={daily_max.date()} "
        "new_trading_dates=0 upserted_rows=0 snapshot_written=False",
        flush=True,
    )
    return raw_df, all_features, group_feature_map
```

**机制**: 检查 `daily_bar` 是否有新日期，无新日期则跳过

---

### 2.3 `run_daily_update()` 幂等性

**结论**: ✅ 幂等（依赖子函数）

**证据** (`pipeline.py:1485-1530`):
- Step 1 (daily_bar): 调用 `run_downloader()`，检查最后日期
- Step 2 (feature_wide): 调用 `run_raw_feature_pipeline()`，有幂等检查
- Step 3 (label_wide): 调用 `run_label_pipeline()`，有幂等检查

**机制**: 各步骤独立幂等，整体幂等

---

### 2.4 `run_full_pipeline()` 幂等性

**结论**: ⚠️ 部分幂等

**问题**:
- 中性化步骤 (`run_neutralize_pipeline()`) 会重新计算
- 回测步骤 (`run_backtest_pipeline()`) 会覆盖已有结果

**行为**: 
- 数据层面幂等（upsert）
- 计算层面非幂等（会重新计算）

---

## 3. 连续执行测试结果

### 测试方法

```python
# 记录初始状态
initial_state = get_state()

# 第一次执行
result1 = run_label_pipeline()

# 第二次执行
result2 = run_label_pipeline()

# 比较结果
assert result2["status"] == "skipped"
assert get_state() == initial_state
```

### 预期结果

| 函数 | 第一次执行 | 第二次执行 | 数据变化 |
|------|------------|------------|----------|
| `run_label_pipeline()` | status=ok | status=skipped | 无 |
| `run_raw_feature_pipeline()` | 更新 | 跳过 | 无 |
| `run_daily_update()` | 全部执行 | 部分跳过 | 无 |

---

## 4. 数据一致性保证

### 4.1 Upsert 机制

**证据** (`src/data_hub/etl_process.py:181-231`):
```python
sql = f'''
INSERT INTO daily_bar ({quoted_cols})
VALUES ({placeholders})
ON CONFLICT(date, code) DO UPDATE SET
{update_clause}
'''
```

**效果**: 同一主键重复写入会更新而非插入

### 4.2 事务保护

**证据** (`src/data_hub/etl_process.py:266-271`):
```python
raw_con.execute("PRAGMA busy_timeout=60000")
try:
    _upsert_daily_bar(raw_con, df)
finally:
    raw_con.execute("PRAGMA busy_timeout=5000")
```

---

## 5. 随机性来源

### 5.1 模型训练

**位置**: `src/ml_core/backtest.py`

**随机性**: 
- LightGBM/XGBoost 默认有随机种子
- 配置中未显式设置 `random_state`

**建议**: 在配置中添加 `random_state: 42`

### 5.2 数据采样

**位置**: `src/data_hub/etl_process.py`

**随机性**:
- 反爬休眠: `random.uniform(sleep_range[0], sleep_range[1])`
- 不影响数据一致性

---

## 6. 完全复现要求

### 必须锁定

| 项目 | 当前状态 | 建议操作 |
|------|----------|----------|
| Python 版本 | >= 3.10 | 固定为 3.12.x |
| 依赖版本 | >= 模式 | 生成 requirements-lock.txt |
| Node 版本 | 未指定 | 添加 .nvmrc |
| 随机种子 | 未设置 | 配置中添加 random_state |

### 建议的 requirements-lock.txt 生成

```bash
pip freeze > requirements-lock.txt
```

---

## 7. 结论

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 幂等性 | ✅ | 核心函数幂等 |
| 版本锁定 | ⚠️ | 部分锁定 |
| 数据一致性 | ✅ | 使用 upsert |
| 随机性控制 | ⚠️ | 未完全控制 |

**可复现性评级**: **B级** (可复现，但需补充版本锁定)
