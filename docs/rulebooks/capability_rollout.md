# Capability Rollout

本分册定义 RearMirror 在主线可运行之后，如何逐步激活结果消费、HPO、stacking 与 frontend/workbench 等后续能力，避免项目永远只做下一轮主线迭代，也避免一次性大改打断当前阶段模型。

---

## 1. Decision Point Requirement

- 当某一业务主线轮次已经具备 `iteration_result_brief.md`，且 Session A 准备做“阶段收口 / 下一阶段激活 / 下一轮因子调整”裁定时，A 必须额外完成一次 capability-rollout decision。
- 这次 decision 只允许两个结果：
  - `defer_capability_slice`
  - `activate_capability_slice`
- 若选择 `defer_capability_slice`，必须在 `WORKLOG.md` 写清楚延后原因，避免团队长期默认“只做下一轮主线”。
- 若选择 `activate_capability_slice`，必须通过新的 `HANDOFF.md` 显式激活能力切片，而不是靠聊天意图或隐式共识启动。

## 2. Allowed Capability Slices

- 允许按以下默认顺序逐步引入：
  1. `iteration_artifacts_and_result_routing`
  2. `multimodel_hyperparameter_optimization`
  3. `model_stacking`
  4. `frontend_workbench`
- 若要跳过默认顺序，Session A 必须在 `WORKLOG.md` 解释为什么当前项目成熟度已经允许这样做。
- 除非 A 已显式激活，否则这些能力项只作为 `docs/open_items.md` 中的后续事项存在，不自动进入当前业务 handoff。

## 3. Activation Criteria

### 3.1 `iteration_artifacts_and_result_routing`
- 进入前提：
  - 当前结果简报机制已经稳定可用
  - 团队已经感受到 QA 结果分散、结果消费不友好，或需要统一轮次目录

### 3.2 `multimodel_hyperparameter_optimization`
- 进入前提：
  - 至少已经存在一轮边界清楚的单模型或多模型 baseline
  - 当前问题不再是“连同边界 baseline 都跑不通”

### 3.3 `model_stacking`
- 进入前提：
  - 单模型基线和 HPO 口径已经基本稳定
  - 已能获得可比较的同边界预测输出

### 3.4 `frontend_workbench`
- 进入前提：
  - 结果目录结构与 summary / brief 输出已经稳定至少若干轮
  - 前端将消费什么文件、什么字段已经基本冻结
- 技术栈约束：
  - 前端框架：**React**（强制）
  - 后端 API：FastAPI（已实现 `api/` 目录）
  - 数据格式：JSON（后端提供，前端消费）
  - 状态管理：根据复杂度选择 React Query / Zustand / Redux
  - 图表库：根据需求选择 ECharts / Recharts / Plotly.js

## 4. Workflow Integration

- 能力切片一旦被激活，仍然继续遵守现有 A / B / D / C 流程，而不是绕开阶段模型另起一套流程。
- Session B / C / D 不得自行从当前业务迭代跳出并启动新能力建设；但当 A 已显式激活 capability slice 后，后续角色也不应继续把它当成“只是未来想法”。
- `HANDOFF.md` 若激活 capability slice，必须显式写出：
  - 当前能力切片名称
  - 它服务的业务主线阶段
  - 为什么现在激活，而不是继续纯主线迭代

