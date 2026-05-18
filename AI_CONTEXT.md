# 0. Document Charter (文档定位与准入规则)

## 0.1 Purpose (用途)
- `AI_CONTEXT.md` 是 RearMirror 的长期规则总入口，只承载以下四类信息：
  1. 冷启动必须知道的协作宪法
  2. 相对稳定的角色边界与阶段字典
  3. 三大文件的读取顺序与事实来源优先级
  4. 各长期规则分册的索引与准入边界
- 详细长期规则不再继续横向堆进本文件；需要展开的主题应收敛到 `docs/rulebooks/` 下的分册。
- `AI_CONTEXT.md` 不是战情板，不记录“本轮正在修什么”“当前谁被打回”“最近哪条测试失败”。
- 任何依赖当前代码状态、当前测试结果、当前分支进度才能成立的内容，都不得写入本文件。

## 0.2 Admission Rules (准入标准)
只有同时满足以下条件的内容，才能写入 `AI_CONTEXT.md`：
- 不绑定某一轮任务、某一个缺陷单、某一次评审结论
- 30 天后仍大概率有效
- 不需要通过运行测试或翻日志来判断真伪
- 对多角色协作或量化结果正确性有长期约束价值
- 属于冷启动入口、阶段字典、角色边界或分册路由规则

以下内容绝对禁止写入 `AI_CONTEXT.md`：
- 当前阻塞任务、当前优先级、当前修复清单
- 某条测试当前失败或通过的结论
- “某模块已完成迁移/尚未完成迁移”这类易过期状态判断
- 单次性能排障结论、单次事故复盘摘要
- 详细模板、长示例、领域细则的完整展开；这类内容应进入分册

## 0.3 Source of Truth (事实来源优先级)
- 运行事实以当前代码、当前配置、当前测试、当前日志为准。
- `AI_CONTEXT.md` 定义“应该成立什么”；它不证明“此刻真的成立”。
- `HANDOFF.md` 记录“这一轮要做什么、失败证据是什么、完成标准是什么”。
- `WORKLOG.md` 记录“这一轮实际发生了什么、谁在什么时候做了什么、基于什么证据做出什么判断”。
- `docs/rulebooks/` 记录长期细则；它们和 `AI_CONTEXT.md` 共同组成长期规则体系。

## 0.4 Edit Authority (编辑权限)
- `AI_CONTEXT.md` 默认仅允许 Session C 修改。
- 允许修改本文件的触发条件只有三类：
  1. 架构边界变更
  2. 长期业务约束变更
  3. 协作协议或分册路由规则本身变更

## 0.5 Reading Scope Policy (读取范围规则)
- `AI_CONTEXT.md` 是长期规则入口文件，不要求每轮执行全文复读；默认采用”主宪章最小必读集合 + 按阶段补读分册 + 少数场景全文复读”的读取机制。
- 新 session 或冷启动时，必须按以下顺序读取：
  1. `AI_CONTEXT.md` 全文 -- 确认角色边界、阶段字典、读取顺序与三大文件语义
  2. `HANDOFF.md` 全文 -- 判断当前球权、当前流程、必做项和最小读取范围
  3. `docs/rulebooks/collaboration_rulebook.md` 全文 -- 理解交接模板、动作类型、日志协议
  4. `docs/roles/session_{角色}.md` -- 理解本角色的允许动作、禁止动作、完成信号
- `collaboration_rulebook.md` 是协作的核心规则，定义了 HANDOFF.md 的强制模板、动作类型语义、WORKLOG.md 的追加格式和打回规则；任何角色冷启动时必须读取，不可跳过。
- 在读完上述必读文件之前，不应默认展开 `WORKLOG.md` 或其他长期分册。
- 只有当 `HANDOFF.md` 明确要求补读时，才按其声明的”所属轴线 / 当前流程 / 最小读取范围”定向读取 `WORKLOG.md` 和其他 rulebook；最后再回到代码、配置、测试和日志核对事实。
- `HANDOFF.md` 虽然可以约束”最小读取范围”，但不得把 `AI_CONTEXT.md` 或 `collaboration_rulebook.md` 完全排除在外；任何可正式流转的工单都必须给出最小宪法读取切片。
- 若当前任务本身是三大文件一致性审计、协议修订或交接机制排障，则不适用”只按最小读取范围补读”的简化；执行者必须按 `AI_CONTEXT.md -> collaboration_rulebook.md -> HANDOFF.md -> WORKLOG.md` 的顺序直接读取，再补读相关 rulebook，最后回到代码、配置、测试和日志核对事实。
- 若当前问题同时涉及阶段切换、长期规则修订、运行模式调整、跨阶段冲突或结构性文档/代码冲突，则必须全文复读本文件与相关分册，而不是只读当前工单。
- `WORKLOG.md` 默认不做全文读取；除非命中全文复读条件，否则应优先读取与当前 `HANDOFF.md` 所属轴线、当前流程、当前 `round_id` 或当前治理切片直接相关的记录。
- 本文件的推荐阅读映射如下：
  1. 协作与球权判断：优先阅读第 1 章
  2. 交接模板、动作类型、日志协议：**必读** `docs/rulebooks/collaboration_rulebook.md`
  3. 项目基线、数据层级、流程门禁：阅读 `docs/rulebooks/project_baseline.md`
  4. 业务硬约束：阅读 `docs/rulebooks/business_invariants.md`
  5. 工程与文件治理约束：阅读 `docs/rulebooks/engineering_constraints.md`
  6. 角色动作边界与完成信号：**必读** `docs/roles/` 下对应角色卡片
  7. 面向决策者的结果输出与迭代汇报：阅读 `docs/rulebooks/result_reporting.md`
  8. 主线结果成熟后的能力演进裁定：阅读 `docs/rulebooks/capability_rollout.md`
  9. 研究轮次的探索性资产口径与候选迭代方法：阅读 `docs/rulebooks/research_iteration_policy.md`

---

# 1. Collaboration Constitution (协作宪法)

## 1.0 Quick Start (接手入口)
- 接手时先读 `AI_CONTEXT.md` 的主宪章部分，先明确角色边界、阶段字典和三大文件语义；随后再看 `HANDOFF.md` 第一行状态标签判断当前球权。
- 新 session 或冷启动时，默认先读 `AI_CONTEXT.md` 的主宪章部分，随后再读 `HANDOFF.md`；若读完 `HANDOFF.md` 仍不足以判断下一步，则说明发送方未把当前工单写到可接手程度。
- 正常执行顺序默认是：A 定义阶段，B 建设能力，D 调用与验证，C 审计复核，A 阶段收口；未经 A 明确启用，不得自行切换到下一阶段。
- 第 1 章的核心用途只有三件事：判断当前谁该接球、判断当前事项属于哪个阶段、判断该继续推进、打回还是回到 A 重裁。
- 任何“当前阶段”表述都应尽量同时说明两件事：业务主线当前停留在哪一阶段，以及当前激活工单属于哪个阶段或治理切片。
- 若同一阶段已在 B 与 D 之间多轮往返，或问题已经升级为资源预算、事务边界、收尾策略、运行模式等阶段设计问题，默认先回到 A，而不是继续在 B/D 之间循环。

## 1.1 File Boundary (文件边界)
- `AI_CONTEXT.md`：长期规则总入口、角色边界、阶段字典、读取顺序与分册索引
- `docs/rulebooks/`：长期细则分册，承载详细模板、项目基线、业务硬约束、工程治理规则
- `docs/roles/`：各角色的 repo 内职责卡片；用于把“角色能做什么、不能做什么、拿到球后必须推进什么”沉回仓库，而不是继续堆到 prompt
- `HANDOFF.md`：唯一合法的任务流转单，记录当前轮次的状态标签、任务边界、证据与完成标准
- `WORKLOG.md`：追加式工作日志，记录跨轮次可审计的执行轨迹、关键证据、阶段结论与打回原因
- `docs/open_items.md`：轻量残余问题与治理债务登记处，用于承接本轮不阻塞阶段验收、但需要后续明确归属的未收口事项
- 判断“长期规则本来应该怎样”先回到 `AI_CONTEXT.md`，再按需进入对应分册；判断“现在谁该动”再看 `HANDOFF.md`；判断“之前为什么这样走到这里”最后回到 `WORKLOG.md`。

## 1.2 Role Responsibilities (角色职责)
- Session A：负责定义每个新阶段的目标、边界、完成标准、非目标、回退条件，并对阶段是否正式结束、是否允许进入下一阶段做最终裁决；不得直接落地业务实现。
- Session B：负责根据 A 已确认的阶段约束开发或修复业务能力；不得擅自改写架构原则，但可以补充与本次修改直接相关的最小回归测试。
- Session D：负责调用系统执行当前阶段、运行测试、产生产物、收集统计、记录复现命令与证据；不主动重写业务实现，也不替代 B 承担正式开发职责。
- Session C：负责未来数据泄露审查、规则一致性验收、阶段审计意见输出，以及长期规则文件维护；C 可以建议放行或打回，但不能越过 A 直接开启下一阶段。
- 更细的“允许动作 / 禁止动作 / 完成信号 / 非球权待命行为”统一下沉到 `docs/roles/session_a.md`、`session_b.md`、`session_c.md`、`session_d.md`。

## 1.2.1 Stage Activation Protocol (阶段启用协议)
RearMirror 的任何新阶段都必须按以下顺序推进：

1. A 先启用阶段：A 必须先定义本阶段的目标、边界、完成标准、证据要求、非目标与回退条件。
2. B 负责建设能力：若本阶段需要新增、修复或调整系统能力，由 B 负责开发实现。
3. D 负责调用与验证：当能力已具备后，由 D 负责实际运行本阶段流程、执行测试、生成产物、记录统计与复现命令。
4. C 负责审计复核：C 依据 A 预先定义的阶段标准审查证据，并输出通过、打回、阻塞或有条件通过的审计意见。
5. A 负责阶段收口：只有 A 能正式宣布当前阶段结束，并明确是否开启下一阶段。

强制规则：
- C 的“通过”仅代表审计通过或建议放行，不等于下一阶段已被正式激活。
- 未经 A 明确确认，不得把“建议放行”写成“正式放行”。
- 阶段切换时，默认应先回到 Session A 做新阶段规划，再决定交给 B 还是 D。

## 1.2.2 Development vs Execution Boundary (开发与执行边界)
- 写能力属于 B；用能力属于 D。
- 若“落盘”指的是开发落盘能力，归 B；若“落盘”指的是调用既有能力产生产物并验收结果，归 D。
- 除非 A 明确认定当前阶段不需要开发工作，否则 D 不得以测试名义替代 B 完成业务实现。
- B 不应长期代替 D 承担正式执行验证、产物生成与证据留痕；若 B 临时执行验证，必须在 `WORKLOG.md` 说明原因。

## 1.2.3 A Re-entry Mechanism (A 强制重进场机制)
以下场景一旦出现，当前阶段不得继续只在 B 与 D 之间循环，必须先回到 A 重新裁决：

1. 同一阶段已发生两轮及以上 `B -> D -> B` 或 `D -> B -> D` 往返，但阶段仍未收口。
2. 根因已不再是单点实现错误，而是资源预算、事务边界、落盘策略、阶段拆分方式、正式验收目标等架构或阶段设计问题。
3. D 已能证明“继续等待”与“直接终止”都缺少明确标准，例如没有时间预算、内存上限、I/O 上限、允许的降级策略或半成品处置规则。
4. 正式运行已出现明显资源性风险，例如内存逼近系统上限、长事务拖垮数据库读写、半成品资产持续堆积、继续重跑可能破坏环境稳定性。
5. 当前阻塞需要决定“是否继续坚持全量正式路径”“是否先拆成更小的正式子阶段”“是否允许暂时移除 compat 收尾作为验收前提”，而这些决定不属于 B 或 D 的权限范围。

强制规则：
- 命中以上任一条件时，`HANDOFF.md` 默认应改为 `[WAITING_FOR_A_ARCHITECT]`，而不是继续直接交给 B 或 D。
- B 可以提供实现选项，D 可以提供运行证据，但只有 A 能重新定义当前阶段的目标、验收口径、资源预算、终止条件与下一棒角色。
- 若当前分歧已经从“本轮是否能继续”降级为“后续还要不要补治理/补兼容/补清理”，且它不再阻塞当前阶段验收，则不应继续让当前 `HANDOFF.md` 长期挂着；应由发送方把残余事项转记到 `docs/open_items.md`，再让当前工单按既定结论收口或流转。

## 1.2.4 Operationalization Rule (实际使用运行规则)
当某阶段暴露出资源瓶颈、长事务、超大中间态或正式落盘退化问题时，A 的职责不只是在本轮给出“怎么验证”，还必须判断该问题对后续真实使用的影响，并在需要时定义长期运行方案。

强制规则：
- 若某条正式路径在验证时已经触及机器资源上限、数据库退化区间或不可接受的运行时长，则默认不能把它视为“验证通过后自然可用”；必须单独回答“以后真实使用时怎么跑”。
- “验证入口”和“实际使用入口”可以相同，也可以不同；但若不同，A 必须明确两者的目标、前提、资源要求和允许的降级方式。
- B 不负责决定业务侧默认运行模式，D 不负责决定生产口径；这类长期运行策略必须由 A 定义，必要时由 C 复核并写入长期规则。

## 1.2.5 Project Stage Model (项目阶段模型)
RearMirror 的推进必须同时区分两条轴线：业务主线阶段与治理侧线阶段。三大文件在描述“当前阶段”时，必须共享同一套阶段字典，不得各自发明阶段名。

### 1.2.5.1 Business Mainline Stages (业务主线阶段)
默认业务主线阶段如下：

1. `raw_to_canonical`              -- 数据下载与规范化入库
2. `raw_feature`                   -- 原始特征工程 (全量因子)
3. `factor_selection_and_neutralize` -- 因子筛选与截面中性化
4. `label_and_dataset`             -- 标签生成与数据集构建
5. `train_and_backtest`            -- 模型训练与 Walk-Forward 回测
6. `hyperparameter_optimization`   -- 超参数优化 (可编辑增强，使用 Optuna)
7. `model_stacking`                -- 模型堆叠 (可选增强，默认跳过)
8. `analysis_and_delivery`         -- 因子分析与结果交付
9. `formalization_and_promotion`   -- 正式化与资产晋升

阶段说明：
- `hyperparameter_optimization`：可编辑增强阶段，基于 Optuna 实现超参搜索，由 Session A 显式激活。
- `model_stacking`：可选增强阶段，在单模型基线稳定后可选启用。

### 1.2.5.2 Governance Stage (治理侧线阶段)
默认治理侧线阶段为：

1. `governance_and_operationalization`

治理侧线允许继续拆为更小切片，例如：
- `file_paths_and_output_routing`      -- 文件路径与输出路由
- `result_output_mechanism`            -- 迭代结果输出机制 (JSON/Markdown + API)
- `frontend_interface`                 -- 前端接口层 (React + FastAPI)
- `runtime_modes_and_degradation`      -- 运行模式与降级策略
- `protocol_alignment`                 -- 协议对齐与兼容性
- `factor_incremental_reuse`           -- 因子增量复用策略
- `cleanup_authorization_and_dryrun`   -- 清理授权与干跑验证

强制规则：
- 不得把治理问题伪装成业务主线阶段继续推进。
- 不得因为当前工单落在治理侧线，就误判业务主线已经自动前进到下一阶段。
- `HANDOFF.md`、`WORKLOG.md` 与相关审计结论中，若写“当前阶段”，应尽量同时区分“当前业务主线停留位置”和“当前激活工单所属阶段/切片”。
- Session A 负责定义和调整阶段字典；Session C 负责将阶段字典维护到本文件；Session B 与 Session D 不负责自行发明新的长期阶段体系。

### 1.2.5.3 Current Stage Expression (当前阶段表达规则)
任何时点都应分别表达以下两个状态：

1. 当前业务主线停留在哪个阶段。
2. 当前激活工单属于哪个阶段或哪个治理切片。

强制规则：
- 不得只写一句“当前阶段是什么”而不区分业务主线与当前工单。
- 若当前工单属于治理侧线，应明确写出它属于治理切片推进，不等于业务主线自动收口或自动前进。
- `HANDOFF.md` 的 `结论` 与 `WORKLOG.md` 的 `action/findings/next` 应尽量维持同一表达口径，避免一个写业务阶段、另一个只写临时切片名。

### 1.2.5.4 Stage Authority Rules (阶段定义权限规则)
- Session A 负责定义和调整长期阶段字典，并决定当前事项属于业务主线阶段还是治理侧线切片。
- Session C 负责将阶段字典、阶段表达规则和与之相关的日志/读取规则维护到 `AI_CONTEXT.md`。
- Session B 与 Session D 不负责自行发明新的长期阶段体系；若现有阶段不够表达当前问题，应通过 `HANDOFF.md` 或审计意见请求回到 Session A 重裁。
- 若 `HANDOFF.md`、`WORKLOG.md` 与当前代码事实对“当前阶段”产生冲突，必须先回到长期规则和当前事实核对，不得用口头约定替代阶段定义。

### 1.2.5.5 Research Workbench Transition Discipline (研究工作台式演进约束)
- RearMirror 的长期形态默认是 human-driven research workflow，而不是一次性改造成 black-box full automation。
- 结果归档目录、HPO、stacking、frontend/workbench 等后续能力，默认都按 staged rollout 引入；未被 `HANDOFF.md` 显式激活前，不自动成为当前阶段阻塞项。
- 对未来能力的记录优先落在 `WORKLOG.md` 与 `docs/open_items.md`，只有当某项能力已经变成长期稳定的协作规则时，才上升到 `AI_CONTEXT.md` 或长期 rulebook。
- 演进方式优先采用 additive integration：先复用现有 versioned asset、QA 产物和阶段门禁，再逐步增加更易用的人工驱动入口，而不是先推翻当前阶段模型。
- 当某一轮业务主线已经形成可供人类决策的结果输出时，Session A 不应永远只做“继续下一轮主线”这一种默认裁定；A 必须显式决定是继续主线，还是激活一个后续能力切片。
- 在 `formalization_and_promotion` 被显式激活前，`factor_selection_and_neutralize` 到 `analysis_and_delivery` 之间形成的 versioned asset、compat 产物和下游结果，默认都按 exploratory / experimental assets 对待，不按长期正式资产对待。
- 当前研究轮次默认不采用“从全量因子池里机械删除几个弱因子再重跑”作为唯一迭代方法；新的候选轮次应以研究假设、候选组合和与上一轮的增量比较为主。

## 1.3 State Tags (状态标签)
`HANDOFF.md` 第一行必须是以下四个状态标签之一：
- `[WAITING_FOR_A_ARCHITECT]`
- `[WAITING_FOR_B_CODER]`
- `[WAITING_FOR_D_QA]`
- `[WAITING_FOR_C_AUDITOR]`

Agent 被唤醒后必须先检查 `HANDOFF.md` 第一行。若标签不属于本角色，立即停止操作。

## 1.4 Three-File Constitutional Rules (三大文件宪法规则)
- `HANDOFF.md` 是当前工单的唯一合法流转单，必须整文件覆写，不得追加历史块。
- `HANDOFF.md` 必须固定包含：动作类型、所属轴线、当前流程、关联业务主线、最小读取范围、结论、必做项、证据、完成标准、非目标、发送方、接收方。
- `HANDOFF.md` 的最小读取范围中，`AI_CONTEXT.md` 不得缺席；至少必须给出能覆盖球权、阶段归属和日志协议的最小宪法切片。
- `HANDOFF.md` 的最小读取范围中，`WORKLOG.md` 也不得缺席；至少必须指出当前流程、当前治理切片或当前 `round_id` 的相关记录。
- `HANDOFF.md` 的最小读取范围应优先对齐为三类入口：`WORKLOG.md` 相关记录、`AI_CONTEXT.md`/rulebook 规则切片、代码/测试/脚本入口；允许在单项内合并多个同类文件，但不应继续自由漂移成任意结构。
- `WORKLOG.md` 是追加式审计轨迹，不允许按轮次整文件覆写；角色切换、阶段放行/打回、长期规则修订后必须留痕。
- 任何会影响阶段结论的 `HANDOFF.md` 更新，都应在 `WORKLOG.md` 留下一条对应记录。
- 若执行者因用户显式指令临时越过当前 `HANDOFF.md` 球权完成动作，允许先执行，但动作结束后必须先在 `WORKLOG.md` 留下“用户直接改派/显式覆盖”的事实记录，再把 `HANDOFF.md` 回正到当前真实球权与真实阶段状态，之后才允许恢复正式流转。
- 任何角色只要覆写 `HANDOFF.md`，或修改 `AI_CONTEXT.md` / `WORKLOG.md` / `docs/rulebooks/` 中的协作协议相关内容，就必须在正式流转前运行 `tools/validate_three_files.py`；校验未通过时不得交接。
- `HANDOFF.md` 的动作类型必须既作为显式字段出现，也在 `结论` 首句保持同一语义前缀；详细模板与动作定义见 `docs/rulebooks/collaboration_rulebook.md`。

## 1.5 Rulebook Map (分册索引)
- `docs/rulebooks/collaboration_rulebook.md`
  - 负责：`HANDOFF.md` 固定模板、动作类型、`WORKLOG.md` 追加格式、记日志时机、回退规则。
- `docs/rulebooks/project_baseline.md`
  - 负责：项目目标、技术栈、核心模块、数据层级、feature/label 配对契约、canonical 契约、端到端流程、流程门禁与各业务阶段门禁卡。
- `docs/rulebooks/business_invariants.md`
  - 负责：时间序列完整性、截面处理纪律、交易现实性、可复现性。
- `docs/rulebooks/engineering_constraints.md`
  - 负责：增量计算、性能原则、运行模式与降级、兼容性与日志、文件生命周期与清理治理。
- `docs/rulebooks/result_reporting.md`
  - 负责：每轮业务迭代必须交付的结果简报、面向决策者的最小指标、分阶段结果输出要求，以及与 `HANDOFF.md` / `WORKLOG.md` 的集成规则。
- `docs/rulebooks/capability_rollout.md`
  - 负责：当主线结果已经成熟到足以做方向裁定时，Session A 如何显式决定”继续主线”还是”激活一个后续能力切片”，以及这些能力切片的默认顺序和进入前提。
- `docs/rulebooks/research_iteration_policy.md`
  - 负责：当前研究轮次的默认资产状态、候选组合式迭代方法、formalization 前后的边界，以及探索性资产后续清理/晋升的口径。
- `docs/rulebooks/subagent_protocol.md`
  - 负责：主 Agent 与 Subagent 的协作方式、Subagent 类型、Prompt 模板、启动方式。
- `docs/roles/`
  - 负责：各角色在当前活跃工单上的允许动作、禁止动作、拿到球后的最小推进义务，以及非球权状态下允许输出的待命摘要口径。
- `docs/open_items.md`
  - 负责：承接当前不阻塞阶段验收、但需要后续继续追踪的残余问题、治理债务和兼容性收尾事项；它不是当前球权文件，也不替代 `HANDOFF.md` / `WORKLOG.md`。
- 进入规则：先读 `AI_CONTEXT.md`，确定球权、阶段、读取顺序后，再按当前事项进入对应分册；不得反过来把分册当作新的总入口。

---

# 2. Maintenance Rules (维护规则)

## 2.1 How To Update Split Rulebooks (何时更新规则体系)
仅在以下情况下更新：
- 项目长期架构发生变化
- 新增或修订长期业务硬约束
- 协作协议、阶段字典或交接规则发生变化
- 现有 `docs/rulebooks/` 分册边界已经明显失衡，需要重新分拆或归并

## 2.2 What Stays Out Of AI_CONTEXT (哪些内容不要继续塞回主文件)
以下内容应写入 `HANDOFF.md`、`WORKLOG.md`、测试报告、任务系统、独立复盘文档或相应分册，而不是继续写回主文件：
- 当前失败用例
- 当前性能瓶颈
- 当前阻塞模块
- 本轮修复计划
- 本轮是否允许进入下一阶段
- 详细模板、长示例、领域细则的大段展开

## 2.3 Writing Style (写法要求)
- 写约束和判定规则，少写当前结论。
- 写系统设计目标与必须满足的条件，少写目前已经完成什么。
- 若某句必须依赖当前运行状态才能成立，就不该出现在长期规则文件中。
- 主文件优先保留路由、边界和裁决规则；长篇细则优先进入相应分册。
- 对于 future roadmap，优先写“分阶段引入、非阻塞、与现有流程的兼容边界”，而不是把未来目标写成当前已全部生效的事实。

## 2.4 Split Discipline (拆分纪律)
- 新长期规则首先判断是否影响冷启动、球权判断、阶段字典、事实来源优先级或分册路由；只有命中这些主宪章问题，才进入 `AI_CONTEXT.md`。
- 若规则主要影响详细模板、项目基线、业务硬约束或工程治理，应直接进入对应 rulebook，而不是先堆到主文件再事后拆走。
- 若某个 rulebook 持续膨胀到难以定向补读，应继续在 `docs/rulebooks/` 内部分册，而不是把细则回灌到 `AI_CONTEXT.md`。
- 后续若继续重构，应优先让“读取顺序”“阶段字典”“日志结构”和“文件治理规则”彼此对齐，而不是继续横向堆积新规则。
