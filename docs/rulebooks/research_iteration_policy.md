# Research Iteration Policy

本分册定义 RearMirror 当前研究轮次的默认资产口径与迭代方法，避免把探索性结果误写成正式资产，也避免继续以“从全量因子池中机械删几个弱因子”作为默认迭代方式。

---

## 1. Asset Status Rule

- 在 `formalization_and_promotion` 阶段被 Session A 显式激活之前，`factor_selection_and_neutralize`、`label_and_dataset`、`train_and_backtest`、`analysis_and_delivery` 产出的 versioned asset、compat 产物、模型结果与分析结果，默认都属于 exploratory / experimental assets。
- exploratory / experimental assets 允许：
  - 保留版本线
  - 被后续轮次引用作比较基线
  - 被记录在 `WORKLOG.md`、QA 目录与结果简报中
- exploratory / experimental assets 不允许被默认写成：
  - 长期正式资产
  - 已最终定稿的生产口径
  - 不再需要后续 formalization 的资产

## 2. Iteration Method Rule

- 当前研究轮次默认不采用“从全部因子中删除几个最弱因子再重跑”作为唯一或默认迭代方法。
- 新一轮候选研究至少应明确以下内容：
  1. 当前研究假设
  2. 当前候选因子组合或候选子集
  3. 与上一轮相比到底改了什么
  4. 为什么这些改动有研究意义，而不只是机械删因子
- 若当前轮仍需要删除或新增少量因子，也必须把它写成候选组合变更，而不是自动等价成“正式方案继续收敛”。

## 3. Promotion Rule

- 只有在 `formalization_and_promotion` 阶段被显式激活并通过审计后，某一轮研究产物才可以被写成正式资产。
- 进入 `formalization_and_promotion` 前，Session A 必须先确认：
  - 该轮结果不是偶然的单轮测试结论
  - 因子组合、模型口径、结果输出口径已经足够稳定
  - 后续是否需要保留、迁移或清理旧 exploratory / experimental assets 已经有明确计划

## 4. Cleanup Rule

- 当前 exploratory / experimental assets 不应立刻无痕删除，因为它们仍承载研究血缘与比较依据。
- 但它们也不应被长期冒充正式资产。后续应在 `formalization_and_promotion` 或专门治理切片中，显式决定：
  - 保留哪些轮次作为研究基线
  - 迁移哪些结果到正式目录
  - 清理哪些历史 exploratory / experimental assets
- 任何批量删除都必须继续遵守现有清理治理规则与 `WORKLOG.md` 留痕要求。

## 5. Reporting Rule

- `iteration_result_brief.md` 对 `factor_selection_and_neutralize` 轮次的描述，默认应使用：
  - 候选组合
  - 探索性结果
  - 实验性版本化资产
- 除非已经进入 `formalization_and_promotion`，否则不应默认使用“正式 feature_set / 正式策略方案已确定”这类表述。

