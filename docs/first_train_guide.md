# 首次训练指南 (first_train_guide.md)

## 1. 前提条件

- 数据库 `data/quant.db` 已存在且包含数据
- 配置文件 `configs/base_config.yaml` 存在

## 2. 最小可行配置

当前 `configs/base_config.yaml` 中已包含推荐参数，无需修改即可运行。

**关键配置项**:

```yaml
# 标签配置
label:
  name: label_5d_ret
  horizon: 5
  method: pctChg_sum

# 回测配置
backtest:
  train_window: 252      # 训练窗口 (1年)
  gap: 20                # 训练/测试间隔
  test_step: 63          # 测试步长 (约3个月)
  top_k: 30              # 持仓股票数
  friction_cost: 0.002   # 交易成本 (0.2%)

# 模型配置
model:
  active: xgboost
  xgboost:
    n_estimators: 200
    max_depth: 6
    learning_rate: 0.1
```

## 3. 训练步骤

### 步骤 1: 验证数据状态

```bash
python -c "
import sqlite3
con = sqlite3.connect('data/quant.db')

print('数据状态:')
for table in ['daily_bar', 'feature_wide', 'label_wide']:
    result = con.execute(f'SELECT MAX(date), COUNT(*) FROM {table}').fetchone()
    print(f'  {table}: max={result[0]}, count={result[1]}')
"
```

**预期输出**:
```
数据状态:
  daily_bar: max=2026-04-17, count=4274723
  feature_wide: max=2026-04-17, count=3974812
  label_wide: max=2026-04-10, count=3957115
```

---

### 步骤 2: 执行全链路训练

```bash
python -c "
from src.config_loader import load_config
from pipeline import run_full_pipeline

cfg = load_config()
result = run_full_pipeline(cfg)
print(result)
"
```

**或分步执行**:

```bash
# 1. 特征工程 (已完成则跳过)
python -c "
from pipeline import run_raw_feature_pipeline
run_raw_feature_pipeline()
"

# 2. 中性化
python -c "
from pipeline import run_neutralize_pipeline
run_neutralize_pipeline()
"

# 3. 回测
python -c "
from pipeline import run_backtest_pipeline
run_backtest_pipeline()
"
```

---

### 步骤 3: 验证训练结果

```bash
python -c "
import sqlite3
con = sqlite3.connect('data/quant.db')

print('训练结果:')
# predictions
result = con.execute('SELECT COUNT(*), MAX(date) FROM predictions').fetchone()
print(f'  predictions: {result[0]} 行, max={result[1]}')

# nav_daily
result = con.execute('SELECT COUNT(*), MAX(date) FROM nav_daily').fetchone()
print(f'  nav_daily: {result[0]} 行, max={result[1]}')

# model_registry
result = con.execute('SELECT COUNT(*) FROM model_registry').fetchone()
print(f'  model_registry: {result[0]} 个模型')
"
```

---

## 4. 预期训练结果

| 指标 | 预期值 |
|------|--------|
| Sharpe Ratio | >= 1.0 |
| Annual Return | >= 5% |
| Max Drawdown | <= 20% |
| ICIR | >= 0.5 |

**证据** (当前已验证):

```
# 来自历史训练结果
Sharpe Ratio: 1.8094
Annual Return: 9.80%
Max Drawdown: -1.28%
```

---

## 5. 常见问题

### Q1: label_wide 落后怎么办？

```bash
python -c "
from pipeline import run_label_pipeline
run_label_pipeline()
"
```

### Q2: 训练中断怎么办？

重新执行 `run_backtest_pipeline()`，会覆盖已有结果。

### Q3: 如何调整参数？

编辑 `configs/base_config.yaml`，修改对应配置项。

---

## 6. 验证脚本

```bash
# 完整验证
python -c "
from src.config_loader import load_config
from pipeline import run_daily_update

cfg = load_config()
result = run_daily_update(cfg)
print(result)
"
```

**预期输出**:
```
=== 数据新鲜度校验 ===
daily_bar     2026-04-17
feature_wide  2026-04-17  OK
label_wide    2026-04-10  OK (合理滞后 horizon=5)
STATUS: OK
```
