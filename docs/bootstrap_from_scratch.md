# 从零部署指南 (bootstrap_from_scratch.md)

## 1. 环境要求

| 项目 | 版本要求 | 实际验证版本 |
|------|----------|--------------|
| Python | >= 3.10 | 3.12.3 ✅ |
| Node.js | >= 18.x | 未锁定 ⚠️ |
| 操作系统 | Windows/Linux | Windows 11 ✅ |

## 2. 部署步骤

### Step 1: 克隆代码 (1 分钟)

```bash
git clone <repo_url> RearMirror
cd RearMirror
```

**产物**: 项目源码

---

### Step 2: 安装 Python 依赖 (3-5 分钟)

```bash
pip install -e .
pip install -r requirements.txt
```

**证据**:
```
# requirements.txt (当前版本)
pandas>=2.0
numpy>=1.24
pyarrow>=14.0
...
lightgbm>=4.0
xgboost>=2.0
baostock>=0.8
akshare>=1.10
fastapi>=0.109.0
uvicorn>=0.27.0
```

**问题**:
- ⚠️ 版本使用 `>=` 而非 `==`，未完全锁定
- ⚠️ 无 `requirements-lock.txt` 或 `pip freeze` 输出

**产物**: Python 虚拟环境

---

### Step 3: 安装前端依赖 (2-3 分钟)

```bash
cd frontend
npm install
```

**证据**:
```
# frontend/package.json
"dependencies": {
  "react": "^19.2.4",
  "echarts": "^6.0.0",
  ...
}
"devDependencies": {
  "typescript": "~6.0.2",
  "vite": "^8.0.4"
}
```

**问题**:
- ✅ 有 `package-lock.json` (lockfileVersion: 3)
- ⚠️ 使用 `^` 版本，次要版本可变

**产物**: `frontend/node_modules/`

---

### Step 4: 创建必要目录 (1 分钟)

```bash
mkdir -p data/raw data/cache data/features data/results
```

**产物**: 数据存储目录结构

---

### Step 5: 准备初始数据 (可选，30 分钟 - 数小时)

#### 方案 A: 从已有数据库复制

```bash
# 复制现有数据库
cp /path/to/quant.db data/quant.db
```

**产物**: `data/quant.db` (约 4.5 GB)

#### 方案 B: 从零下载数据

```bash
python -c "
from src.config_loader import load_config
from src.data_hub import run_downloader, merge_and_clean

cfg = load_config()
run_downloader(cfg)  # 下载 15 年数据，约 30-60 分钟
merge_and_clean(cfg)
"
```

**产物**:
- `data/raw/zz500_10y_daily_clean.parquet` (332 MB)
- `data/raw/stock_industry_map.parquet` (42 KB)

---

### Step 6: 构建特征矩阵 (10-30 分钟)

```bash
python -c "
from pipeline import run_raw_feature_pipeline
from src.config_loader import load_config
run_raw_feature_pipeline(load_config())
"
```

**产物**:
- `data/features/feature_store.parquet` (804 MB)
- SQLite `feature_wide` 表 (3,974,812 行)

---

### Step 7: 生成标签 (1-2 分钟)

```bash
python -c "
from pipeline import run_label_pipeline
from src.config_loader import load_config
run_label_pipeline(load_config())
"
```

**产物**: SQLite `label_wide` 表 (3,957,115 行)

---

### Step 8: 训练模型 (5-15 分钟)

```bash
python -c "
from pipeline import run_backtest_pipeline
from src.config_loader import load_config
run_backtest_pipeline(load_config())
"
```

**产物**:
- SQLite `predictions` 表
- SQLite `nav_daily` 表
- SQLite `model_registry` 记录

---

### Step 9: 启动服务 (即时)

```bash
# 后端
uvicorn api.main:app --host 0.0.0.0 --port 8000

# 前端开发模式
cd frontend && npm run dev

# 前端生产模式
cd frontend && npm run build
# 将 dist/ 部署到静态服务器
```

**产物**: 可访问的 Web 服务

---

## 3. 时间估算

| 步骤 | 最少时间 | 最多时间 |
|------|----------|----------|
| 克隆代码 | 1 分钟 | 2 分钟 |
| Python 依赖 | 3 分钟 | 5 分钟 |
| 前端依赖 | 2 分钟 | 3 分钟 |
| 创建目录 | 1 分钟 | 1 分钟 |
| 下载数据 | 30 分钟 | 2 小时 |
| 构建特征 | 10 分钟 | 30 分钟 |
| 生成标签 | 1 分钟 | 2 分钟 |
| 训练模型 | 5 分钟 | 15 分钟 |
| 启动服务 | 即时 | 即时 |
| **总计** | **约 1 小时** | **约 3 小时** |

---

## 4. 关键产物清单

| 路径 | 大小 | 必须性 |
|------|------|--------|
| `data/quant.db` | 4.5 GB | 必须 |
| `data/raw/zz500_10y_daily_clean.parquet` | 332 MB | 可选缓存 |
| `data/raw/stock_industry_map.parquet` | 42 KB | 必须 |
| `data/features/*.parquet` | ~1 GB | 可选缓存 |
| `frontend/dist/` | 1.6 MB | 生产部署 |
| `configs/base_config.yaml` | 16 KB | 必须 |

---

## 5. 验证命令

```bash
# 验证 Python 环境
python -c "import pandas, numpy, lightgbm, xgboost; print('OK')"

# 验证数据库
python -c "
import sqlite3
con = sqlite3.connect('data/quant.db')
print(con.execute('SELECT COUNT(*) FROM daily_bar').fetchone())
"

# 验证前端
cd frontend && npm run build
```

---

## 6. 已知问题

1. **版本未完全锁定**: `requirements.txt` 使用 `>=` 而非 `==`
2. **无 pip freeze 输出**: 缺少 `requirements-lock.txt`
3. **Node 版本未指定**: 无 `.nvmrc` 文件
4. **数据库必须预置**: 无自动初始化脚本
