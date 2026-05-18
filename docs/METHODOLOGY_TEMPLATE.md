# AI 协作研究方法论

> 本文档抽象自 RearMirror 量化研究平台的协作框架，可复用于数据驱动型研究项目（如天文学、地球科学、生物信息学等）。

---

## 目录

1. [核心理念](#1-核心理念)
2. [四大角色](#2-四大角色)
3. [三大文件协议](#3-三大文件协议)
4. [阶段模型](#4-阶段模型)
5. [数据层级设计](#5-数据层级设计)
6. [业务约束体系](#6-业务约束体系)
7. [流程门禁](#7-流程门禁)
8. [工程约束](#8-工程约束)
9. [天文学研究适配示例](#9-天文学研究适配示例)
10. [实施清单](#10-实施清单)

---

## 1. 核心理念

### 1.1 设计原则

| 原则 | 说明 |
|------|------|
| **单文件真理** | 所有配置收口于一个 YAML 文件，避免散落 |
| **明确球权** | 任何时候都清楚"谁该动"，避免多人同时改同一处 |
| **可追溯决策** | 每个阶段结论都有证据链支撑 |
| **增量可复现** | 增量路径与全量路径语义一致 |
| **门禁驱动** | 不满足门禁条件不得进入下一阶段 |

### 1.2 文件分层

```
项目根目录/
├── AI_CONTEXT.md          # 长期规则总入口（冷启动必读）
├── HANDOFF.md             # 当前工单流转单（谁该接球）
├── WORKLOG.md             # 追加式审计日志（历史轨迹）
├── docs/
│   ├── rulebooks/         # 长期规则分册
│   ├── roles/             # 角色卡片
│   └── open_items.md      # 残余事项登记
├── configs/
│   └── base_config.yaml   # 配置唯一真理来源
└── tools/
    └── validate_three_files.py  # 三大文件校验脚本
```

---

## 2. 四大角色

### 2.1 角色定义

| 角色 | 职责 | 典型动作 |
|------|------|----------|
| **Session A** | 架构师 | 定义阶段、裁定收口、分配球权 |
| **Session B** | 开发者 | 实现能力、修复缺陷、补充测试 |
| **Session C** | 审计者 | 审计证据、维护规则、输出意见 |
| **Session D** | 执行者 | 运行验证、收集证据、生成产物 |

### 2.2 角色卡片模板

每个角色应有一份 `docs/roles/session_X.md`：

```markdown
# Session X Role Card

Session X 是 [项目名] 的 [职责定位]。

职责定位:
- [核心职责 1]
- [核心职责 2]

允许动作:
- 当 `HANDOFF.md` 为 `[WAITING_FOR_X_XXX]` 时，[具体动作]
- [其他允许动作]

禁止动作:
- 不[禁止项 1]
- 不[禁止项 2]

拿到球后的最小推进义务:
- 不能只[消极行为]；必须至少完成以下之一：
  1. [义务 1]
  2. [义务 2]

非球权状态:
- 若当前第一行不是 `[WAITING_FOR_X_XXX]`，只允许输出待命摘要：
  - 当前阶段
  - 当前球权归属
  - 为什么现在还不该由 X 出手
- 非球权状态下不得改文件。

完成信号:
- [完成条件 1]
- [完成条件 2]
```

### 2.3 角色流转规则

```
正常流转: A → B → D → C → A
故障回退: D → B (测试失败) 或 C → B (审计失败)
阻塞待证: 任意 → A (需要重新裁决)
```

**强制规则**：
- C 的"通过"仅代表审计通过，不等于下一阶段已被激活
- 未经 A 明确确认，不得把"建议放行"写成"正式放行"
- 阶段切换时，默认应先回到 A 做新阶段规划

---

## 3. 三大文件协议

### 3.1 AI_CONTEXT.md（长期规则总入口）

**用途**：承载冷启动必须知道的协作宪法、角色边界、阶段字典、读取顺序。

**准入标准**：
- 不绑定某一轮任务或缺陷单
- 30 天后仍大概率有效
- 不需要运行测试来判断真伪
- 对多角色协作有长期约束价值

**禁止写入**：
- 当前阻塞任务、当前优先级
- 某条测试当前失败或通过的结论
- 单次性能排障结论、单次事故复盘

**必含章节**：
1. 文档定位与准入规则
2. 协作宪法（角色职责、阶段启用协议）
3. 状态标签定义
4. 三大文件宪法规则
5. 规则分册索引

### 3.2 HANDOFF.md（当前工单流转单）

**用途**：回答"当前球在谁手里、下一步做什么、基于什么证据"。

**强制规则**：
- 第一行必须且只能是状态标签
- 必须整文件覆写，不得追加历史块
- 必须显式声明动作类型、所属轴线、当前流程
- 必须给出最小读取范围

**固定模板**：

```markdown
[WAITING_FOR_A_ARCHITECT]

动作类型:
[正常流转 / 故障回退 / 阻塞待补证据]

所属轴线:
[business_mainline / governance_side]

当前流程:
[阶段名或治理切片名]

关联业务主线:
[若属于治理切片，写服务的业务阶段；无则写 无]

最小读取范围:
1. WORKLOG.md 相关记录范围
2. AI_CONTEXT.md / rulebook 规则章节
3. 代码/测试/脚本入口

结论:
[一句话说明当前是否可继续推进及原因]

必做项:
1. [本轮必须完成的事项]
2. [按优先级继续列出]

证据:
- [测试名 / 日志片段 / 文件路径]

完成标准:
- [达到什么条件后才允许交给下一个角色]

非目标:
- [本轮明确不要做的事]

发送方: [角色]
接收方: [角色]
```

**动作类型**：
1. **正常流转**：当前阶段已完成，球正常传给下游
2. **故障回退**：执行失败，球退回上游修复
3. **阻塞待补证据**：无法判定，需补充证据或重新裁决

### 3.3 WORKLOG.md（追加式审计日志）

**用途**：回答"谁在什么时候做了什么、基于什么证据、得出什么结论"。

**强制规则**：
- 必须追加式写入，不得整文件覆写
- 每条记录必须完整自洽，可脱离上下文单独阅读
- 重点记录动作、证据和结论

**固定模板**：

```markdown
## [时间戳] | [角色] | [阶段] | [状态]
- round_id: [本轮唯一标识]
- action: [本次执行的动作]
- inputs: [本次基于哪些文件、配置、测试或数据]
- findings: [观察到的事实或发现的问题]
- evidence: [测试名、日志片段、文件路径、关键输出]
- decision: [通过 / 打回 / 阻塞 / 继续观察]
- next: [下一步交给谁或下一动作是什么]
```

**强制记日志时机**：
- 角色切换或正式交接前后
- 阶段被打回、阻塞、放行时
- 运行了关键测试、审计检查、数据验收脚本后
- 修改了长期规则、阶段门禁、数据层契约后

### 3.4 校验脚本

`tools/validate_three_files.py` 应至少校验：
- HANDOFF.md 第一行是否为有效状态标签
- HANDOFF.md 是否包含所有必填字段
- WORKLOG.md 文件头格式是否正确
- 三大文件之间是否存在明显矛盾

---

## 4. 阶段模型

### 4.1 阶段定义模板

每个阶段应在 `AI_CONTEXT.md` 或规则分册中定义：

| 字段 | 说明 |
|------|------|
| 阶段名 | 唯一标识 |
| 进入前提 | 必须满足的条件 |
| 交付物 | 本阶段必须产出的内容 |
| 最低证据 | 必须留痕的最小证据 |
| 允许前进条件 | 什么情况下可进入下一阶段 |

### 4.2 阶段启用协议

```
1. A 定义阶段：目标、边界、完成标准、非目标、回退条件
2. B 建设能力：开发或修复实现
3. D 执行验证：运行测试、生成产物、记录证据
4. C 审计复核：审查证据，输出通过/打回/阻塞意见
5. A 阶段收口：正式宣布阶段结束，决定是否开启下一阶段
```

### 4.3 A 强制重进场机制

以下场景必须回到 A 重新裁决：

1. 同一阶段已发生两轮以上 `B → D → B` 往返但未收口
2. 根因已升级为资源预算、事务边界、阶段拆分方式等架构问题
3. 运行已出现资源性风险（内存上限、长事务等）
4. 需要决定"是否拆分子阶段"、"是否允许降级"等超出 B/D 权限的事项

---

## 5. 数据层级设计

### 5.1 标准五层架构

| 层级 | 名称 | 职责 | 生命周期 |
|------|------|------|----------|
| Layer 1 | 原始层 | 保存下载/采集的原始数据 | 长期保留 |
| Layer 2 | 规范化层 | 统一 schema、校验、去重 | 长期保留 |
| Layer 3 | 特征层 | 派生研究特征 | 版本化保留 |
| Layer 4 | 标签层 | 定义预测目标 | 版本化保留 |
| Layer 5 | 实验层 | 训练、评估、血缘 | 按实验隔离 |

### 5.2 层级契约

**原始层 → 规范化层**：
- 原始层保真，不修改
- 规范化层是唯一正式数据入口
- 失败即阻断，不默默降级

**规范化层 → 特征层**：
- 特征层不自行发明底层口径
- 任何解释以规范化层为准
- 特征层独立版本化

**特征层 ↔ 标签层**：
- 独立版本线，不互相覆盖
- 统一主键对齐
- 差异必须可解释

**特征+标签 → 实验层**：
- 只消费上游标准资产
- 实验血缘可追溯

### 5.3 路径纪律

```
data/
├── raw/           # Layer 1: 原始数据
├── canonical/     # Layer 2: 规范化数据
├── features/      # Layer 3: 特征
├── labels/        # Layer 4: 标签
├── results/       # Layer 5: 实验结果
├── cache/         # 可重建缓存
└── logs/          # 运行日志

experiments/       # 按实验 ID 隔离的产物
qa/                # QA 临时产物
tools/             # 工具与脚本
```

---

## 6. 业务约束体系

### 6.1 约束分类

| 类型 | 来源 | 示例 |
|------|------|------|
| 时间完整性 | 领域 | 时间序列不泄露未来数据 |
| 数据一致性 | 领域 | 截面处理纪律 |
| 现实性约束 | 领域 | 交易成本、可执行性 |
| 可复现性 | 工程 | 同配置复现结果 |

### 6.2 约束表达方式

每条约束应：
1. 写明"必须/严禁"或"必须满足以下条件"
2. 说明违反后果
3. 指向配置中的控制参数（如有）

**示例**：

```markdown
## 时间完整性约束

1. 严禁未来数据泄露；所有标签、特征、训练窗口必须按时间对齐。
2. Walk-Forward 回测中的 gap 不得小于预测 horizon。
3. 违反此约束的实验结果视为无效，不得用于决策。
```

---

## 7. 流程门禁

### 7.1 门禁卡模板

每个业务阶段应有门禁卡：

```markdown
### 阶段名

进入前提:
- [前提条件 1]
- [前提条件 2]

本阶段交付物:
- [交付物 1]
- [交付物 2]

最低证据:
- [证据 1]
- [证据 2]

允许前进条件:
- [条件 1]
- [条件 2]
```

### 7.2 门禁执行规则

1. 全流程第一道门禁是原始数据验证
2. 下游阶段不得绕过上游验收
3. 每进入新阶段，必须由 A 明确写出目标、标准、非目标、回退条件
4. C 完成审计后，不得直接交给 B/D 启动下一阶段；必须回到 A

---

## 8. 工程约束

### 8.1 增量计算规则

1. 增量计算目标是减少重复工作，不改变语义
2. 增量路径必须明确 warmup 边界
3. 增量路径与全量路径需要不同实现时，必须验证一致性

### 8.2 运行模式

| 模式 | 用途 | 特点 |
|------|------|------|
| formal | 正式全量 | 完整资产、完整验证 |
| shared_machine | 资源受限降级 | 裁剪范围、减少内存 |
| qa | 临时验证 | 产物写入 qa 目录 |

### 8.3 文件生命周期

| 类别 | 生命周期 | 删除授权 |
|------|----------|----------|
| 正式资产 | 长期保留 | 仅 A 定义边界后可归档 |
| 实验产物 | 按实验隔离 | 可归档，不默认删除 |
| QA 临时产物 | 用完可清 | D 可执行，需留痕 |
| 缓存 | 可重建 | D 可执行，需确认无引用 |
| 日志 | 可轮转 | 按规则清理 |

---

## 9. 天文学研究适配示例

### 9.1 项目定位

> 面向 [特定天体/波段/任务] 的数据驱动研究平台

### 9.2 阶段模型适配

```markdown
业务主线阶段:

1. raw_to_canonical
   - 原始观测数据下载与规范化入库
   - 进入前提: 明确观测目标、时间范围、数据源
   - 交付物: 规范化的观测数据表

2. calibration
   - 仪器校准、背景扣除、数据清洗
   - 进入前提: 规范化层已通过门禁
   - 交付物: 校准后的科学数据

3. feature_extraction
   - 天体特征提取（流量、位置、形态等）
   - 进入前提: 校准数据已具备
   - 交付物: 特征矩阵

4. label_generation
   - 标签生成（分类标签、红移、物理参数等）
   - 进入前提: 特征集已确定
   - 交付物: 标签矩阵

5. model_training
   - 模型训练与验证
   - 进入前提: 数据集已构建
   - 交付物: 训练好的模型、预测结果

6. analysis_and_publication
   - 结果分析与论文产出
   - 进入前提: 模型结果已具备
   - 交付物: 分析报告、图表、论文草稿
```

### 9.3 数据层级适配

```markdown
Layer 1 - 原始层:
- 原始 FITS 文件、望远镜观测日志
- 路径: data/raw/

Layer 2 - 规范化层:
- 统一格式后的观测数据表
- 路径: data/canonical/

Layer 3 - 特征层:
- 提取的天体特征（星等、颜色、形态参数等）
- 路径: data/features/

Layer 4 - 标签层:
- 分类标签、红移、物理参数等
- 路径: data/labels/

Layer 5 - 实验层:
- 模型、预测结果、分析报告
- 路径: data/results/
```

### 9.4 业务约束适配

```markdown
## 时间完整性约束（时域天文）

1. 光变曲线分析中，严禁使用未来数据预测过去
2. 训练/验证集划分必须按观测时间切分
3. gap 必须大于预测 horizon

## 数据一致性约束

1. 不同波段的观测必须统一时间系统（JD/MJD）
2. 星等系统必须明确标注（AB/Vega）
3. 位置坐标必须统一参考系

## 物理真实性约束

1. 特征值必须在物理合理范围内
2. 流量测量必须考虑信噪比阈值
3. 红移估计必须考虑宇宙学约束

## 可复现性约束

1. 同配置必须能复现分析结果
2. 原始数据、处理参数、模型配置必须可追溯
3. 禁止手工修改中间产物
```

### 9.5 配置文件示例

```yaml
# configs/base_config.yaml

# 观测配置
observation:
  survey: "LSST"                    # 巡天项目
  target: "variable_stars"          # 研究目标
  bands: ["u", "g", "r", "i", "z"]  # 观测波段
  start_date: "2020-01-01"
  end_date: "2025-12-31"
  sky_region:                       # 天区范围
    ra_min: 0.0
    ra_max: 360.0
    dec_min: -90.0
    dec_max: 0.0

# 数据处理
data_processing:
  calibration: "standard"           # 校准方式
  background_subtraction: true
  source_detection:
    threshold: 5.0                  # 信噪比阈值
    min_pixels: 10

# 特征工程
features:
  active_features: ["light_curve", "colors", "morphology"]
  time_series_windows: [7, 30, 90]  # 天

# 标签定义
label:
  name: "variable_type"
  classes: ["eclipsing", "cepheid", "rr_lyrae", "delta_scuti", "mira"]
  source: "catalog_crossmatch"

# 模型配置
model:
  active: "random_forest"
  random_forest:
    n_estimators: 200
    max_depth: 15

# 验证配置
validation:
  method: "time_based_split"
  train_ratio: 0.7
  gap_days: 30
```

---

## 10. 实施清单

### 10.1 初始化步骤

```bash
# 1. 创建目录结构
mkdir -p data/{raw,canonical,features,labels,results,cache,logs}
mkdir -p docs/{rulebooks,roles}
mkdir -p configs tools experiments qa

# 2. 创建核心文件
touch AI_CONTEXT.md HANDOFF.md WORKLOG.md
touch docs/open_items.md
touch configs/base_config.yaml
touch tools/validate_three_files.py

# 3. 创建角色卡片
touch docs/roles/session_{a,b,c,d}.md

# 4. 创建规则分册
touch docs/rulebooks/{collaboration_rulebook,project_baseline,business_invariants,engineering_constraints}.md
```

### 10.2 第一轮启动

```markdown
1. 在 AI_CONTEXT.md 中定义项目定位、阶段字典、角色边界
2. 创建四个角色卡片
3. 编写 collaboration_rulebook.md（可直接复用本文档模板）
4. 编写 project_baseline.md（定义数据层级、技术栈）
5. 编写 business_invariants.md（定义领域约束）
6. 创建 base_config.yaml（定义所有关键参数）
7. 编写 validate_three_files.py 校验脚本
8. 初始化 HANDOFF.md 为 `[WAITING_FOR_A_ARCHITECT]`
9. 在 WORKLOG.md 写下第一条启动记录
```

### 10.3 日常运行

```markdown
每个研究迭代:

1. A 定义本轮阶段目标，更新 HANDOFF.md
2. B 实现或修复，更新代码和测试
3. D 运行验证，收集证据，更新 WORKLOG.md
4. C 审计证据，输出意见
5. A 裁定是否收口，是否进入下一阶段
6. 若形成用户可见结果，输出结果简报
```

### 10.4 校验脚本模板

```python
#!/usr/bin/env python3
"""
tools/validate_three_files.py
校验三大文件格式与一致性
"""
import re
import sys

def validate_handoff():
    """校验 HANDOFF.md"""
    with open("HANDOFF.md", "r", encoding="utf-8") as f:
        content = f.read()

    # 检查状态标签
    valid_tags = [
        "[WAITING_FOR_A_ARCHITECT]",
        "[WAITING_FOR_B_CODER]",
        "[WAITING_FOR_C_AUDITOR]",
        "[WAITING_FOR_D_QA]",
    ]

    first_line = content.strip().split("\n")[0]
    if first_line not in valid_tags:
        print(f"ERROR: HANDOFF.md 第一行必须是状态标签，当前为: {first_line}")
        return False

    # 检查必填字段
    required_fields = [
        "动作类型:",
        "所属轴线:",
        "当前流程:",
        "最小读取范围:",
        "结论:",
        "必做项:",
        "证据:",
        "完成标准:",
        "发送方:",
        "接收方:",
    ]

    for field in required_fields:
        if field not in content:
            print(f"ERROR: HANDOFF.md 缺少必填字段: {field}")
            return False

    print("OK: HANDOFF.md 格式正确")
    return True

def validate_worklog():
    """校验 WORKLOG.md"""
    with open("WORKLOG.md", "r", encoding="utf-8") as f:
        content = f.read()

    # 检查文件头
    if not content.startswith("# WORKLOG"):
        print("ERROR: WORKLOG.md 必须以 '# WORKLOG' 开头")
        return False

    print("OK: WORKLOG.md 格式正确")
    return True

def validate_ai_context():
    """校验 AI_CONTEXT.md 存在"""
    import os
    if not os.path.exists("AI_CONTEXT.md"):
        print("ERROR: AI_CONTEXT.md 不存在")
        return False

    print("OK: AI_CONTEXT.md 存在")
    return True

def main():
    results = [
        validate_handoff(),
        validate_worklog(),
        validate_ai_context(),
    ]

    if all(results):
        print("\n=== 所有校验通过 ===")
        return 0
    else:
        print("\n=== 校验失败 ===")
        return 1

if __name__ == "__main__":
    sys.exit(main())
```

---

## 附录：术语表

| 术语 | 定义 |
|------|------|
| 球权 | 当前谁有权限修改文件和推进状态 |
| 阶段 | 业务主线的一个可定义边界的步骤 |
| 治理切片 | 非主线但必须处理的工程/运维事项 |
| 门禁 | 进入下一阶段必须满足的条件 |
| 版本化资产 | 通过配置哈希唯一标识的数据产物 |
| 血缘 | 实验结果与上游数据/配置的追溯链 |
| warmup | 滚动窗口计算所需的历史数据边界 |
| horizon | 预测目标的未来时间跨度 |
| gap | 训练数据与预测数据之间的隔离带 |
