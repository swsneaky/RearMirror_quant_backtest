# Open Items

本文件用于承接"不再阻塞当前阶段验收，但仍需后续明确归属和收口"的残余问题。

使用规则:
- 这里只记录未收口事项，不记录当前球权；当前球权始终以 `HANDOFF.md` 为准。
- 这里只记录后续需要继续跟踪的事项，不替代 `WORKLOG.md` 的事实轨迹。
- 只有当某问题已经不再阻塞当前阶段放行、打回或回到 A 重裁时，才应从当前 `HANDOFF.md` 中迁出到这里。
- 每条事项必须明确属于业务主线阶段还是治理侧线切片，避免"问题还在，但没人知道归谁"。
- 条目允许被关闭，但不应无留痕直接删除；关闭时在 `状态` 中改为 `closed`，并补一句关闭依据。

推荐模板:

```md
## [open_item_id]
- status: open / blocked / closed
- axis: business_mainline / governance_and_operationalization
- stage_or_slice: [正式业务阶段名或治理切片名]
- related_business_stage: [若属于治理侧线，写其服务或阻塞的业务主线；否则写本阶段名]
- summary: [一句话说明残余问题]
- why_not_blocking_now: [为什么它当前不再阻塞本轮阶段验收]
- required_next_owner: Session A / B / C / D
- required_next_action: [下一轮最先该做的动作]
- evidence: [相关文件 / 日志 / 测试 / 数据检查]
```

---

## 重要说明

以下内容已纳入正式阶段模型，不再作为"残余问题"登记：

| 事项 | 归属 |
|------|------|
| 超参数优化 (HPO，使用 Optuna) | 业务主线阶段 6: `hyperparameter_optimization` (可编辑增强) |
| 模型堆叠 (Stacking) | 业务主线阶段 7: `model_stacking` (可选增强) |
| React 前端 | 治理切片: `frontend_interface` |
| 结果输出机制 | 治理切片: `result_output_mechanism` |
| 因子增量复用 | 治理切片: `factor_incremental_reuse` |
| 探索性资产清理 | 业务主线阶段 9: `formalization_and_promotion` |

这些事项应通过 `HANDOFF.md` 正式激活对应阶段/切片来推进，而不是在本文件中反复跟踪。

---

当前登记:

## [20260414_hpo_scale_enhancement]
- status: open
- axis: business_mainline
- stage_or_slice: hyperparameter_optimization
- related_business_stage: hyperparameter_optimization
- summary: HPO 可行性测试仅 2 trials，生产环境建议扩大到 50-100 trials 以获得更优参数配置。
- why_not_blocking_now: 功能已验证通过，当前最佳参数 (Sharpe Ratio 1.8094) 可用；扩大规模是增强项而非功能缺失。
- required_next_owner: Session B
- required_next_action: 当模型性能需进一步优化时，运行扩大规模的 HPO 试验 (n_trials=50-100)。
- evidence: `data/results/hpo/hpo_xgboost_20260414_002703_summary.json` (n_trials: 2)

## [20260409_neutralize_compat_residuals]
- status: closed
- axis: governance_and_operationalization
- stage_or_slice: protocol_alignment
- related_business_stage: factor_selection_and_neutralize
- summary: 历史上 `226` 因子口径下的 compat 残余错配已不再成立；截至 `20260410_next_round_factor_adjustment`，当前 formal asset 与 compat 输出已在 `221` 特征边界对齐。
- why_not_blocking_now: 该事项已由 Session A 在 `2026-04-11 09:38` 基于当前轮执行与审计证据正式关闭。当前 `zz500_alpha158_neutralized.parquet`、`feature_wide`、`label_wide`、`feature_store.parquet`、`label_store.parquet` 均与 `feature_set__fa6df92714e6` / `label_set__3896aeaf202a` 对齐，因此不再需要单独激活 `protocol_alignment` 来承接旧残余。
- required_next_owner: 无
- required_next_action: 无
- evidence: `WORKLOG.md` Session D `20260410_next_round_factor_adjustment_execution`；`WORKLOG.md` Session C `20260410_next_round_factor_adjustment_c_audit`；`WORKLOG.md` Session A `20260411_label_and_dataset_reactivation`

## [20260409_label_dataset_materialization_runtime]
- status: closed
- axis: governance_and_operationalization
- stage_or_slice: runtime_modes_and_degradation
- related_business_stage: train_and_backtest
- summary: 当前 SQLite 环境下，基于显式 versioned asset 的全量 `COUNT(*)` join 与 5-feature 全量 `build_train_dataset()` 在 15 分钟内均未返回，说明后续 full materialization 的运行时边界尚未被裁定。
- why_not_blocking_now: 该问题已不再作为残余事项登记；Session A 已在 `HANDOFF.md` 中把它正式提升为当前活跃治理切片 `runtime_modes_and_degradation`，转由三大文件主流程继续跟踪。
- required_next_owner: Session A
- required_next_action: 已由 Session A 裁定并提升为当前 `HANDOFF.md` 活跃工单；后续以当前治理切片的 `WORKLOG.md` / `HANDOFF.md` 为准。
- evidence: `WORKLOG.md` Session D `20260409_label_dataset_explicit_asset_qa`；`WORKLOG.md` Session C `20260409_label_dataset_c_audit`；`src/data_layer/dataset_builder.py`

## [20260411_random_forest_shared_machine_runtime_observation]
- status: open
- axis: governance_and_operationalization
- stage_or_slice: runtime_modes_and_degradation
- related_business_stage: train_and_backtest
- summary: Under the same explicit shared-machine boundary used for `xgboost` and `lightgbm`, `random_forest` completes successfully but takes `1781.8s` on the current shared machine, which is materially slower than the other configured model entries.
- why_not_blocking_now: Session A re-closed `train_and_backtest` at `2026-04-11 20:33` and explicitly classified this slowdown as a governance residual rather than a business-stage blocker. `random_forest` completed successfully, produced a full QA package, and registered `status='done'`, so the slowdown does not invalidate the current 9.5 stage pass or block entry into `analysis_and_delivery`.
- required_next_owner: Session A
- required_next_action: When deciding future approved-entry policy or model-default recommendations, explicitly decide whether `random_forest` remains an allowed shared-machine verification path, needs a separate runtime budget, or should be excluded from the normal approved shared-machine route. Until then, treat it as non-blocking governance debt rather than as the active business-stage gate.
- evidence: `WORKLOG.md` Session D `20260411_train_and_backtest_multimodel_execution`; `WORKLOG.md` Session C `20260411_train_and_backtest_multimodel_c_audit`; `WORKLOG.md` Session A `20260411_analysis_and_delivery_reactivation_multimodel`; `qa/train_and_backtest/session_d_train_backtest_multimodel_summary_20260411/multimodel_summary.json`; `data/quant.db` `experiment_run`

## [20260411_segmented_neutralize_post_tail_observation]
- status: open
- axis: governance_and_operationalization
- stage_or_slice: runtime_modes_and_degradation
- related_business_stage: factor_selection_and_neutralize
- summary: After segmented neutralize removed the old opaque "100% complete then black box" behavior, both `formal` and `shared_machine` still retain a traceable post-cross-section tail (`1012.93s` / `1378.58s`) around label generation, store writes, and compat export.
- why_not_blocking_now: The current slice goal was to prove that segmented execution is real, auditable, and same-semantic across modes. That goal is already satisfied, and the current 9.3 business-stage evidence shows no semantic drift, asset-boundary split, or compat/versioned mismatch attributable to this tail.
- required_next_owner: Session A
- required_next_action: When deciding future runtime-budget policy or approved-entry policy, explicitly decide whether this post-tail remains a tracked observation only, needs a dedicated governance slice, or requires new budget rules before a later full-run stage.
- evidence: `WORKLOG.md` Session D `20260411_segmented_neutralize_execution_mode_qa`; `WORKLOG.md` Session C `20260411_segmented_neutralize_execution_mode_c_audit`; `qa/segmented_neutralize_execution_mode/session_d_formal_20260411/summary.json`; `qa/segmented_neutralize_execution_mode/session_d_shared_machine_20260411/summary.json`; `qa/segmented_neutralize_execution_mode/session_d_formal_vs_shared_machine_comparison_20260411.json`

## [20260413_config_enhancement_candidates]
- status: open
- axis: business_mainline
- stage_or_slice: multiple (hyperparameter_optimization, factor_selection_and_neutralize, label_and_dataset)
- related_business_stage: 各归属阶段的增强迭代
- summary: 配置增强候选：(1) ✅ 模型超参数已补全 (2026-04-15)；(2) 回测参数缺失（`benchmark_code`/`max_turnover`/`sector_neutral`）；(3) 因子筛选机制无自动化支持；(4) 标签配置局限（仅支持单周期）。
- why_not_blocking_now: 模型超参数已补全；其余项属于能力增强而非功能缺失。
- required_next_owner: Session A
- required_next_action: 当需要回测参数增强时处理 `benchmark_code`/`max_turnover`/`sector_neutral`；当需要因子筛选自动化或标签多周期时再处理。
- evidence: `configs/base_config.yaml` 模型参数已补全 (lightgbm: early_stopping_round, max_bin, extra_trees, path_smooth 等；xgboost: early_stopping_rounds, max_bin, max_delta_step 等)

## [20260414_port_8000_zombie_process]
- status: closed
- axis: governance_and_operationalization
- stage_or_slice: runtime_modes_and_degradation
- related_business_stage: N/A (基础设施问题)
- summary: 端口 8000 存在僵尸进程占用，导致后端服务无法在该端口启动；需重启系统清理。
- why_not_blocking_now: 用户确认端口 8000 为虚拟机占用，属于正常使用，非僵尸进程；无需处理。
- required_next_owner: 无
- required_next_action: 无
- evidence: 用户反馈 "端口8000好像是虚拟机在用"

## [20260414_frontend_code_splitting]
- status: open
- axis: governance_and_operationalization
- stage_or_slice: frontend_interface
- related_business_stage: N/A (前端优化)
- summary: 前端构建产物未做代码分割优化，bundle.js 体积可能较大；建议后续按页面拆分 chunk。
- why_not_blocking_now: 当前 MVP 页面数量少，构建产物体积可接受；用户体验无明显影响。
- required_next_owner: Session B
- required_next_action: 当前端页面数量增长到 10+ 或首屏加载时间超过 3s 时，激活代码分割优化。
- evidence: `npm run build` 输出: `dist/assets/index.js`
