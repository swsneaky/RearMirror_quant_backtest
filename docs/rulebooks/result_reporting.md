# Result Reporting (结果输出规则)

本分册定义“每一次业务迭代都必须把结果以人类可读形式输出”的长期规则。

---

## 1. Decision Brief Requirement (决策简报要求)

- 任何进入业务主线阶段收口、下一阶段激活或下一轮因子调整裁定的轮次，都必须先形成一份面向决策者的结果简报。
- 结果简报不是替代 QA 产物，而是把本轮最关键的结论、指标和边界压缩成“人能直接判断要不要继续”的交付物。
- 若本轮只有底层日志、Parquet、JSON 指标而没有结果简报，则默认不允许把该轮写成“已向用户展示结果”。
- Session A 在裁定“是否进入下一轮 `factor_selection_and_neutralize`”之前，必须能引用当前轮结果简报；不得只引用原始 QA 文件名而不做结果汇总。

## 2. Required Artifacts (强制产物)

- 每一轮进入业务主线阶段裁定前，当前 QA 目录下至少应包含：
  - `iteration_result_brief.md`
  - `iteration_result_summary.json`
- `iteration_result_brief.md` 面向人类阅读，要求一屏内可看完，优先写结论、关键指标、边界说明、下一步建议。
- `iteration_result_summary.json` 面向程序与审计，要求字段稳定、可被后续对比脚本读取。
- 若阶段本身已产出更详细的 `analysis_summary.json`、`metrics_summary.json`、`dataset_summary.json` 等文件，则结果简报必须引用这些文件，而不是重复造一套孤立指标。

## 3. Minimum Content (最小内容)

所有 `iteration_result_brief.md` 至少必须包含：

1. 当前业务阶段与轮次标识
2. 当前版本化资产边界：
   - `feature_set_id`
   - `label_set_id`
   - 若存在 `runtime_mode`，必须显式写出
3. 当前轮核心结果：
   - 本轮到底变好了、变差了，还是仅完成证据补齐
4. 当前轮关键证据：
   - 最少 3 条关键数字或事实
5. 下一步建议：
   - 保持当前方案 / 进入下一轮因子调整 / 回退修复 / 需要人工裁定
6. 口径边界：
   - 结果成立于什么前提下，不得误写成更强结论

## 4. Stage-Specific Requirements (分阶段最低要求)

### 4.1 `factor_selection_and_neutralize`
- 必须写清：
  - 当前轮显式排除因子
  - 当前轮保留的正向锚点
  - 新的 `feature_set_id`
  - 中性化矩阵行数、特征列数、标签列数、主键重复数
  - compat 与当前实验性版本化资产是否对齐
- 若这是新的候选研究轮次，必须补一句“相对上一轮到底改了什么、研究假设是什么”，避免看起来像机械重复删因子。

### 4.2 `label_and_dataset`
- 必须写清：
  - feature/label 对齐统计
  - dataset 形状、特征数、日期范围、样本数
  - 当前 runtime 边界

### 4.3 `train_and_backtest`
- 必须写清：
  - `ann_excess_return`
  - `information_ratio`
  - `max_drawdown`
  - 运行耗时
  - 关键产物是否完整
- 若是多模型轮次，必须写出模型对比，不得只报一个模型。

### 4.4 `analysis_and_delivery`
- 必须写清：
  - `icir_mean`
  - `median_abs_icir`
  - Top / Bottom 因子
  - 推荐动作与推荐依据
- 若 A 准备据此激活下一轮因子调整，则必须能从简报中直接看出“为什么要删这些因子”。

## 5. Ownership Rules (角色责任)

- Session D 负责在当前 QA 目录内生成或更新结果简报。
- Session C 负责审计结果简报是否与底层 QA 产物、日志和数据库留痕一致。
- Session A 负责在阶段收口或下一轮激活时引用结果简报，并把“为什么继续/为什么回退/为什么换候选组合”说给人听。
- Session B 不负责代替 A 做结果解读，但若当前轮结果需要新增统计能力，B 负责补能力。

## 6. Handoff / Worklog Integration (与 Handoff / Worklog 的集成)

- 当业务主线进入阶段收口、下一阶段激活或下一轮方向裁定时，`HANDOFF.md` 的最小读取范围必须包含当前轮结果简报路径。
- `WORKLOG.md` 中对应的 D、C、A 记录都应在 `evidence` 中引用当前轮结果简报，避免只留下底层 JSON / Parquet 文件名。
- 若当前轮没有结果简报，A 不应把“进入下一轮因子调整”写成已经对用户充分汇报过的结论。
- 当当前轮已经具备足够做方向裁定的结果简报时，A 除了回答“继续主线还是进入下一轮”之外，还应显式回答一次“是否激活新的 capability slice”；若选择暂不激活，也应在 `WORKLOG.md` 留下 defer 理由。
