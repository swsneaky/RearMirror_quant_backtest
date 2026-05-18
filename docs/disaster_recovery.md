# 灾难恢复指南 (disaster_recovery.md)

## 1. 场景一：数据库损坏

### 症状
- SQLite 报错 "database disk image is malformed"
- 查询失败或返回空结果
- 写入失败

### 恢复步骤

#### 方案 A：从备份恢复

```bash
# 检查备份文件
ls -la data/quant.db.bak*

# 恢复
cp data/quant.db.bak_20260418 data/quant.db
```

**备份位置**: `data/quant.db.bak_YYYYMMDD` (当前有 44GB 备份)

#### 方案 B：从 Parquet 重建

```bash
# 1. 删除损坏的数据库
rm data/quant.db

# 2. 从 parquet 文件重建
python -c "
from src.config_loader import load_config
from src.data_layer.db import get_connection
import pandas as pd

cfg = load_config()

# 加载原始数据
df = pd.read_parquet('data/raw/zz500_10y_daily_clean.parquet')

# 重新初始化数据库 (需要手动创建表)
# ...
"
```

**注意**: 完整重建需要重新运行全流程

---

## 2. 场景二：特征表损坏

### 症状
- `feature_wide` 查询失败
- 特征列数据异常

### 恢复步骤

```bash
# 1. 检查当前状态
python -c "
import sqlite3
con = sqlite3.connect('data/quant.db')
result = con.execute('SELECT COUNT(*) FROM feature_wide').fetchone()
print(f'feature_wide: {result[0]} 行')
"

# 2. 删除损坏数据
python -c "
import sqlite3
con = sqlite3.connect('data/quant.db')
con.execute('DELETE FROM feature_wide')
con.commit()
print('已清空 feature_wide')
"

# 3. 重新生成
python -c "
from pipeline import run_raw_feature_pipeline
from src.config_loader import load_config
run_raw_feature_pipeline(load_config())
"
```

**耗时**: 约 10-30 分钟

---

## 3. 场景三：标签落后

### 症状
- `label_wide.max(date)` 远小于预期
- 与 `daily_bar` 日期差距过大

### 恢复步骤

```bash
# 1. 检查滞后情况
python -c "
import sqlite3
con = sqlite3.connect('data/quant.db')

daily_max = con.execute('SELECT MAX(date) FROM daily_bar').fetchone()[0]
label_max = con.execute('SELECT MAX(date) FROM label_wide').fetchone()[0]

print(f'daily_bar: {daily_max}')
print(f'label_wide: {label_max}')
print(f'差距: {(daily_max - label_max).days} 天')
"

# 2. 使用统一入口修复
python -c "
from pipeline import run_label_pipeline
from src.config_loader import load_config
result = run_label_pipeline(load_config())
print(result)
"
```

**证据** (`pipeline.py:1082-1180`):
```python
def run_label_pipeline(cfg, incremental=True):
    # 获取目标日期
    target_label_max = daily_max - horizon 个交易日
    
    # 如果已最新，跳过
    if old_label_max >= target_label_max:
        return {"status": "skipped", ...}
    
    # 否则增量更新
    recalc_start = old_label_max - horizon - 2 天
    # ... 重算并 upsert
```

---

## 4. 场景四：训练中断

### 症状
- 回测过程中程序崩溃
- `predictions` 表数据不完整

### 恢复步骤

```bash
# 1. 检查训练状态
python -c "
import sqlite3
con = sqlite3.connect('data/quant.db')

# 检查 experiment_run 状态
result = con.execute('SELECT * FROM experiment_run').fetchall()
for r in result:
    print(f'Experiment: {r}')
"

# 2. 重新运行回测
python -c "
from pipeline import run_backtest_pipeline
from src.config_loader import load_config
run_backtest_pipeline(load_config())
"
```

**注意**: 回测会覆盖已有 `predictions` 数据

---

## 5. 场景五：cum_factor 数据损坏

### 症状
- `cum_factor` 列大量 NULL
- 特征计算产生 NaN

### 恢复步骤

```bash
# 1. 检查 cum_factor 非空率
python -c "
import sqlite3
con = sqlite3.connect('data/quant.db')
result = con.execute('''
    SELECT DATE(date), 
           SUM(CASE WHEN cum_factor IS NOT NULL THEN 1 ELSE 0 END) * 100.0 / COUNT(*)
    FROM daily_bar
    WHERE date >= '2026-04-01'
    GROUP BY DATE(date)
''').fetchall()
for r in result:
    print(f'{r[0]}: {r[1]:.1f}%')
"

# 2. 如果发现问题，删除损坏数据
python -c "
import sqlite3
con = sqlite3.connect('data/quant.db')
con.execute(\"DELETE FROM daily_bar WHERE DATE(date) >= '2026-04-09'\")
con.commit()
print('已删除损坏数据')
"

# 3. 重新下载数据
python -c "
from src.config_loader import load_config
from src.data_hub import run_downloader, merge_and_clean

cfg = load_config()
run_downloader(cfg)
merge_and_clean(cfg)
"

# 4. 重新生成特征和标签
python -c "
from pipeline import run_raw_feature_pipeline, run_label_pipeline
from src.config_loader import load_config

cfg = load_config()
run_raw_feature_pipeline(cfg)
run_label_pipeline(cfg)
"
```

**参考**: `docs/daily_bar_fix_plan.md` 详细修复方案

---

## 6. 预防措施

### 6.1 定期备份

```bash
# 手动备份
cp data/quant.db data/quant.db.bak_$(date +%Y%m%d)

# 或添加到 crontab (Linux)
# 0 2 * * * cp /path/to/data/quant.db /path/to/data/quant.db.bak_$(date +\%Y\%m\%d)
```

### 6.2 使用 WAL 模式

**证据** (`src/data_layer/db.py`):
```python
con.execute("PRAGMA journal_mode=WAL")
con.execute("PRAGMA busy_timeout=5000")
```

### 6.3 数据一致性检查

```bash
# 使用健康检查工具
python tools/check_data_layers.py

# 或手动检查
python -c "
from pipeline import _check_data_freshness
from src.config_loader import load_config
result = _check_data_freshness(load_config())
print(result)
"
```

---

## 7. 恢复时间估算

| 场景 | 恢复方式 | 预计时间 |
|------|----------|----------|
| 数据库损坏 (有备份) | 恢复备份 | 1 分钟 |
| 数据库损坏 (无备份) | 全量重建 | 2-3 小时 |
| 特征表损坏 | 重新生成 | 10-30 分钟 |
| 标签落后 | 增量更新 | 1-2 分钟 |
| 训练中断 | 重新训练 | 5-15 分钟 |
| cum_factor 损坏 | 全量修复 | 1-2 小时 |

---

## 8. 紧急联系

- 项目文档: `docs/`
- 问题追踪: `docs/open_items.md`
- 实施计划: `docs/rearmirror_implementation_plan.md`
