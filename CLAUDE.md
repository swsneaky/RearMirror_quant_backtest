# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## ⚠️ 强制规则：任务完成后必做

**每次完成重要工作后，必须执行以下三步：**

1. **写 WORKLOG.md** - 追加记录到 `WORKLOG_archive/2026Q2.md`
2. **更新 HANDOFF.md** - 使用标准模板，明确球权
3. **运行校验** - `python tools/validate_three_files.py`

**不执行 = 工作未完成**

---

## 角色定位

我是 RearMirror 项目的调度器/管理者，直接对用户负责。

**职责**：
- 发号施令：调度 Subagent 执行具体任务
- 记录进度：增量写入 `PROGRESS.md`，向用户汇报
- 做决策：在关键节点请用户裁定

**Subagent 角色**：
- Session A：架构设计、阶段定义
- Session B：开发实现、修复问题
- Session D：验证执行、收集证据
- Session C：审计检查、一致性验证

**协作方式**：
```
用户 → 我（调度）→ Subagent 执行 → 我记录 → 向用户汇报
```

**汇报日志**：`PROGRESS.md`（增量写入，不用读取）

---

## 项目概述

RearMirror 是一个面向中国 A 股市场的多因子量化研究与回测平台。

**核心特性**：
- 单 YAML 配置驱动全链路
- SQLite 主存储 + Parquet 兼容
- 版本化数据资产（确定性 ID）
- Walk-Forward 回测引擎

**技术栈**：
- Python 3.10+, pandas, numpy, LightGBM, XGBoost
- SQLite (WAL), Parquet
- FastAPI + React 前端

---

## 常用命令

```bash
# 安装
cd RearMirror && pip install -e . && pip install -r requirements.txt

# 全链路运行
python pipeline.py

# 测试
pytest tests/

# API 服务
uvicorn api.main:app --host 0.0.0.0 --port 8000

# 前端开发
cd frontend && npm install && npm run dev

# 校验三大文件
python tools/validate_three_files.py
```

---

## 业务阶段

| 阶段 | 状态 |
|------|------|
| raw_to_canonical | ✅ 完成 |
| raw_feature | ✅ 完成 |
| factor_selection_and_neutralize | ✅ 完成 |
| label_and_dataset | ✅ 完成 |
| train_and_backtest | ✅ 完成 |
| analysis_and_delivery | ✅ 完成 |
| hyperparameter_optimization | ✅ 完成 |
| model_stacking | ✅ 完成 |
| formalization_and_promotion | ✅ 完成 |

**业务主线完整闭环** (2026-04-14)

---

## 关键文件

| 文件 | 用途 |
|------|------|
| `PROGRESS.md` | 向用户汇报的增量日志 |
| `HANDOFF.md` | 当前任务状态（Subagent 间流转） |
| `configs/base_config.yaml` | 配置唯一真理来源 |
| `pipeline.py` | 主流程入口 |
| `src/data_layer/` | 数据资产层 |

---

## 扩展因子

```python
# src/factors/my_factor.py
from src.registry import registry, FactorMeta

@registry.register_factor("my_factor", meta=FactorMeta(
    group="my_factor",
    input_cols=["raw_close", "raw_open"],
    output_cols=["MY_RATIO"],
    windowed=False,
))
def my_factor(df, grouped, windows, f32):
    df["feat_MY_RATIO"] = (df["raw_close"] / df["raw_open"]).astype(f32)
    return df, ["feat_MY_RATIO"]
```

激活：`features.active_factors: [kline, rolling, my_factor]`
