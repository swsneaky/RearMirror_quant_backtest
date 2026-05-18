# 运行环境版本说明 (runtime_versions.md)

本文档记录 RearMirror v0.9-beta (Research Release) 的验证运行环境。

---

## 1. 核心运行时版本

| 组件 | 版本 | 状态 |
|------|------|------|
| Python | 3.12.3 | **已验证** |
| Node.js | 24.12.0 | **已验证** |

> 注：Python 3.10+ 应可兼容，但仅在 3.12.3 上完成完整验证。

---

## 2. 依赖锁定文件

| 文件 | 说明 | 生成时间 |
|------|------|----------|
| `requirements-lock.txt` | Python 依赖冻结清单 | 2026-04-18 |
| `.nvmrc` | Node.js 主版本标记 | 2026-04-18 |

### Python 依赖摘要 (核心组件)

| 包名 | 版本 |
|------|------|
| pandas | 2.3.3 |
| numpy | 2.4.3 |
| lightgbm | 4.6.0 |
| xgboost | 3.2.0 |
| scikit-learn | 1.8.0 |
| fastapi | 0.135.3 |
| pyarrow | 23.0.1 |
| baostock | 0.8.9 |
| akshare | 1.18.40 |
| shap | 0.51.0 |

---

## 3. 操作系统信息

| 项目 | 值 |
|------|------|
| 操作系统 | Windows 11 Home China |
| OS 版本 | 10.0.22631 |
| 平台 | win32 |

---

## 4. 版本语义说明

### 已验证版本
以下版本在发布前验收测试中完成验证：
- Python 3.12.3
- Node.js 24.12.0

### 推荐版本
基于验证结果，建议用户使用以下版本：
- Python: 3.12.x (推荐 3.12.3)
- Node.js: 24.x (推荐 24.12.0)

### 兼容性预期
- Python 3.10+: 预期兼容，但未完成完整验证
- Python 3.13+: 未测试
- Node.js 18+: 预期兼容，前端构建已验证于 24.12.0

---

## 5. 安装指引

### Python 环境
```bash
# 使用 requirements-lock.txt 安装精确版本
pip install -r requirements-lock.txt
```

### Node.js 环境
```bash
# 使用 nvm 安装指定版本
nvm install 24
nvm use 24

# 或使用 .nvmrc 自动切换
nvm use
```

### 前端依赖
```bash
cd frontend
npm install
npm run build
```

---

## 6. 生成方式

本文档由 `pip freeze` 和系统信息收集命令自动生成：

```bash
# Python 版本
python --version

# Node 版本
node --version

# 依赖冻结
pip freeze > requirements-lock.txt

# Node 版本标记
node --version | cut -d'v' -f2 | cut -d'.' -f1 > .nvmrc
```

---

*文档生成日期: 2026-04-18*
*发布版本: v0.9-beta / Research Release*
