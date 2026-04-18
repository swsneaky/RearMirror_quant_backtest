# 发布清单 (release_manifest.md)

## 1. 发布压缩包内容

```
RearMirror-v0.9.0-beta.zip
├── README.md                      # 项目说明
├── LICENSE                        # 许可证
├── requirements.txt               # Python 依赖
├── pyproject.toml                 # 项目配置
│
├── configs/
│   └── base_config.yaml           # 默认配置模板
│
├── src/                           # 源代码
│   ├── config_loader.py
│   ├── pipeline.py (根目录)
│   ├── data_hub/
│   ├── data_layer/
│   ├── feature_engine.py
│   ├── cross_section/
│   ├── label_gen.py
│   ├── ml_core/
│   ├── factors/
│   ├── hpo/
│   └── registry.py
│
├── api/                           # API 服务
│   ├── main.py
│   └── routes/
│
├── frontend/                      # 前端代码
│   ├── package.json
│   ├── package-lock.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── src/
│   └── dist/                      # 构建产物
│
├── tests/                         # 测试代码
│
├── tools/                         # 工具脚本
│   ├── validate_three_files.py
│   ├── check_data_layers.py
│   ├── archive_worklog.py
│   └── diagnose_incremental.py
│
├── docs/                          # 文档
│   ├── AI_CONTEXT.md
│   ├── rearmirror_implementation_plan.md
│   ├── incremental_update_flow.md
│   ├── production_readiness_report.md
│   ├── bootstrap_from_scratch.md
│   ├── first_train_guide.md
│   ├── release_manifest.md
│   ├── disaster_recovery.md
│   ├── reproducibility_report.md
│   └── release_acceptance_checklist.md
│
├── data/                          # 数据目录 (结构，不含实际数据)
│   ├── raw/
│   │   └── stock_industry_map.parquet  # 行业映射 (必须)
│   ├── cache/
│   ├── features/
│   └── results/
```

---

## 2. 不包含的内容

| 内容 | 原因 | 获取方式 |
|------|------|----------|
| `data/quant.db` | 4.5 GB，太大 | 用户自行生成或单独下载 |
| `data/raw/zz500_10y_daily_clean.parquet` | 332 MB | 用户自行下载 |
| `data/features/*.parquet` | 可重新生成 | 用户自行生成 |
| `frontend/node_modules/` | 可安装 | `npm install` |
| `__pycache__/` | 可生成 | 自动创建 |

---

## 3. 必须包含的配置模板

### configs/base_config.yaml (16 KB)

包含所有默认配置：
- 数据库路径
- 数据源配置
- 特征工程参数
- 回测参数
- 模型参数

### data/raw/stock_industry_map.parquet (42 KB)

行业分类映射，5,574 条记录

---

## 4. 发布前检查清单

```bash
# 1. 验证代码完整性
pytest tests/ -q --ignore=tests/test_v2_asset.py
# 预期: 102 passed

# 2. 验证前端构建
cd frontend && npm run build
# 预期: 构建成功，dist/ 存在

# 3. 验证文档完整性
ls docs/*.md
# 预期: 所有文档存在

# 4. 验证配置完整性
ls configs/base_config.yaml
# 预期: 文件存在

# 5. 验证必要数据文件
ls data/raw/stock_industry_map.parquet
# 预期: 文件存在
```

---

## 5. 发布命令

```bash
# 创建发布包 (Git Bash / WSL)
zip -r RearMirror-v0.9.0-beta.zip \
    README.md \
    LICENSE \
    requirements.txt \
    requirements-lock.txt \
    pyproject.toml \
    .nvmrc \
    Dockerfile \
    docker-compose.yml \
    configs/ \
    src/ \
    api/ \
    pipeline.py \
    run_api.py \
    frontend/src/ \
    frontend/package.json \
    frontend/package-lock.json \
    frontend/tsconfig.json \
    frontend/vite.config.ts \
    frontend/dist/ \
    tests/ \
    tools/ \
    docs/ \
    data/raw/stock_industry_map.parquet \
    -x "*.pyc" \
    -x "*__pycache__*" \
    -x "*.egg-info*"
```

```powershell
# 创建发布包 (PowerShell)
Compress-Archive -Path `
    README.md, `
    LICENSE, `
    requirements.txt, `
    requirements-lock.txt, `
    pyproject.toml, `
    .nvmrc, `
    Dockerfile, `
    docker-compose.yml, `
    configs, `
    src, `
    api, `
    pipeline.py, `
    run_api.py, `
    frontend\src, `
    frontend\package.json, `
    frontend\package-lock.json, `
    frontend\tsconfig.json, `
    frontend\vite.config.ts, `
    frontend\dist, `
    tests, `
    tools, `
    docs, `
    data\raw\stock_industry_map.parquet `
    -DestinationPath RearMirror-v0.9.0-beta.zip `
    -Force
```

---

## 6. 文件大小估算

| 内容 | 大小 |
|------|------|
| 源代码 + 配置 | ~2 MB |
| 前端 dist | ~2 MB |
| 文档 | ~500 KB |
| 行业映射 | 42 KB |
| **总计** | **~5 MB** |

---

## 7. 版本标识

在 `pyproject.toml` 中标识：

```toml
[project]
name = "rearmirror"
version = "0.9.0"
```

---

## 8. 发布包类型说明

### 包类型定义

本发布包为 **代码发布包（Source Code Release）**，而非 **完整运行包（Complete Runtime Package）**。

| 类型 | 本包 | 完整运行包 |
|------|------|-----------|
| 源代码 | 包含 | 包含 |
| 配置模板 | 包含 | 包含 |
| 前端构建产物 | 包含 | 包含 |
| 数据库 (quant.db) | **不包含** | 包含 |
| 原始行情数据 | **不包含** | 包含 |
| 特征缓存 | **不包含** | 包含 |
| 开箱即用 | 否 | 是 |

### 解压后立即可用功能

以下功能在解压后无需额外准备即可使用：

1. **代码阅读与研究** - 完整源码、配置、文档
2. **前端预览** - `frontend/dist/` 已构建，可部署静态文件
3. **测试套件执行** - `pytest tests/` 可运行（部分测试需数据库）
4. **API 服务启动** - FastAPI 后端可启动，但无数据返回

### 需要准备数据库后方可使用的功能

以下功能需要先准备 `data/quant.db` 才能正常使用：

1. **数据下载与 ETL** - 生成 `daily_bar` 表
2. **特征工程** - 生成 `feature_wide` 表
3. **标签生成** - 生成 `label_wide` 表
4. **模型训练** - 依赖特征与标签数据
5. **回测执行** - 依赖完整数据链路
6. **因子分析** - 依赖回测结果
7. **Dashboard 数据展示** - 所有图表依赖数据库

### 最少启动路径

```bash
# Step 1: 安装依赖
pip install -r requirements-lock.txt
cd frontend && npm install && npm run build && cd ..

# Step 2: 准备数据库（二选一）
# 方案 A: 从零生成
python -c "
from src.config_loader import load_config
from src.data_hub import run_downloader, merge_and_clean
cfg = load_config()
run_downloader(cfg)
merge_and_clean(cfg)
"

# 方案 B: 获取已有数据库快照
# 将 quant.db 放置到 data/ 目录

# Step 3: 运行完整链路
python pipeline.py

# Step 4: 查看结果
cd frontend && npm run dev
```

### 数据库获取方式

| 方式 | 说明 | 适用场景 |
|------|------|----------|
| 从零生成 | 运行 `run_downloader()` 下载原始数据 | 有网络、有时间 |
| 快照下载 | 单独获取 `quant.db` 文件 | 快速体验、离线环境 |
| 部分数据 | 仅下载必要表数据 | 研究特定功能 |

> 注：完整 `quant.db` 约 4.5 GB，生成时间取决于网络状况。

---

*更新日期: 2026-04-18*
*发布版本: v0.9-beta / Research Release*
