# RearMirror 发布前最后推进任务书（交付给下级 AI 严格执行）

**版本定位**：`v0.9-beta` / `Research Release` / `本地研究版`  
**目标**：在不继续扩大测试范围的前提下，完成发布前最后一轮最小闭环验证，使项目达到“可以发布给技术用户下载使用”的状态。  
**执行原则**：

1. **不再写泛泛评估报告**，只提交“执行结果 + 证据 + 问题清单”。
2. **每一步必须真实执行**，不得用“理论上可以”“预计可行”替代。
3. **每一步都要留痕**：命令、输出、截图级文本证据、产物路径。
4. **遇到失败不得跳过**，必须记录失败原因、定位过程、临时绕过方案与最终状态。
5. **所有反馈必须结构化**，严格使用本文档给出的模板。

---

# 一、当前已知背景（执行时必须遵守）

以下事实已经由现有文档确认，执行时不得随意改写结论：

- 项目已有从零部署指南、首次训练指南、发布清单。`bootstrap_from_scratch.md` 已明确指出：Python 依赖未完全锁定、Node 版本未锁定、无 `requirements-lock.txt`、无自动初始化脚本。  
- `first_train_guide.md` 已给出默认推荐参数与 `run_full_pipeline()` / `run_backtest_pipeline()` 的训练路径，并要求检查 `predictions`、`nav_daily`、`model_registry`。  
- `release_manifest.md` 已明确发布包 **不包含** `data/quant.db` 和大体积原始/特征缓存，因此当前发布物属于“源码/研究版发布包”，不是“解压即用完整包”。  
- `release_acceptance_checklist.md` 已给出测试、前端构建、数据完整性、API、幂等性、文档完整性、发布包验证等检查项，但多数状态尚未打勾。  
- `reproducibility_report.md` 目前给出的可复现性评级为 **B 级**，主要缺口是依赖版本未完全锁定、Node 版本未指定、随机种子未完全控制。  
- `disaster_recovery.md` 已包含数据库损坏、特征表损坏、标签落后、训练中断、`cum_factor` 损坏等恢复方案，可视为“发布时附带的运维/自救文档”。

> 上述事实来自现有 6 份文档，是本次执行的前提，不需要重复调研，只需要补齐最后一轮硬证据和发布动作。

---

# 二、本轮只执行 4 项任务（禁止扩张范围）

本轮只做以下 4 项，不允许擅自新增“大规模测试”“多环境兼容性研究”“重构新功能”。

## 任务 1：跑一遍最小发布验收子集

### 目标
证明当前代码包在“最低必要标准”下可以作为本地研究版发布。

### 必须执行的命令
按顺序执行，除非前一步失败。

#### 1.1 Python 测试
```bash
pytest tests/ -q --ignore=tests/test_v2_asset.py
```

#### 1.2 前端构建
```bash
cd frontend && npm run build
```
执行完成后返回项目根目录。

#### 1.3 三大文件校验
```bash
python tools/validate_three_files.py
```

#### 1.4 数据层状态校验
```bash
python -c "
import sqlite3
con = sqlite3.connect('data/quant.db')
for t in ['daily_bar', 'feature_wide', 'label_wide']:
    r = con.execute(f'SELECT MAX(date), COUNT(*) FROM {t}').fetchone()
    print(f'{t}: max={r[0]}, count={r[1]}')
"
```

### 必须收集的证据
- `pytest` 最终输出末尾 20 行
- `npm run build` 成功输出末尾 20 行
- `validate_three_files.py` 的完整输出
- 3 张表的 `MAX(date), COUNT(*)` 输出

### 通过标准
满足以下条件即可判定任务 1 通过：
- `pytest` 成功结束，无致命失败
- 前端构建成功，`frontend/dist/` 存在
- `validate_three_files.py` 输出正常
- `daily_bar`、`feature_wide`、`label_wide` 均存在且日期关系合理

### 失败处理
- 若 `pytest` 失败：记录失败的测试文件、错误堆栈、是否阻塞发布；**不要立即修一大堆测试**，先判断是否属于本次发布阻塞项。
- 若前端构建失败：记录报错模块、Node 版本、依赖安装状态；只修构建阻塞，不扩大到 UI 重构。
- 若三大文件校验失败：记录是哪一个文件缺失/损坏。
- 若数据层状态异常：记录具体表、日期、行数，并与文档预期对比。

---

## 任务 2：补齐训练结果产物（至少一次）

### 目标
确保发布版本不是“只能打开但没有结果”的空壳；至少生成一轮当前版本可用的训练/回测产物。

### 执行策略
优先执行完整训练：
```bash
python -c "
from src.config_loader import load_config
from pipeline import run_full_pipeline
cfg = load_config()
result = run_full_pipeline(cfg)
print(result)
"
```

如果完整训练因时间或资源原因失败，再执行最小替代方案：
```bash
python -c "
from src.config_loader import load_config
from pipeline import run_backtest_pipeline
cfg = load_config()
result = run_backtest_pipeline(cfg)
print(result)
"
```

### 训练前必须先做的检查
```bash
python -c "
import sqlite3
con = sqlite3.connect('data/quant.db')
for t in ['daily_bar', 'feature_wide', 'label_wide']:
    r = con.execute(f'SELECT MAX(date), COUNT(*) FROM {t}').fetchone()
    print(f'BEFORE {t}: max={r[0]}, count={r[1]}')
for t in ['predictions', 'nav_daily', 'model_registry']:
    try:
        r = con.execute(f'SELECT COUNT(*), MAX(date) FROM {t}').fetchone()
        print(f'BEFORE {t}: count={r[0]}, max={r[1]}')
    except Exception as e:
        print(f'BEFORE {t}: ERROR {e}')
"
```

### 训练后必须做的检查
```bash
python -c "
import sqlite3
con = sqlite3.connect('data/quant.db')
for t in ['predictions', 'nav_daily']:
    r = con.execute(f'SELECT COUNT(*), MAX(date) FROM {t}').fetchone()
    print(f'AFTER {t}: count={r[0]}, max={r[1]}')
r = con.execute('SELECT COUNT(*) FROM model_registry').fetchone()
print(f'AFTER model_registry: count={r[0]}')
"
```

### 必须收集的证据
- 训练前 6 张表状态
- 训练命令完整输出末尾 50 行
- 训练后 `predictions / nav_daily / model_registry` 状态
- 若有关键指标输出（如 Sharpe、Annual Return、Max Drawdown），一并保留
- 若失败，保留完整堆栈与失败阶段（特征 / 标签 / 中性化 / 回测 / 写库）

### 通过标准
满足以下任一条件即可：
- `run_full_pipeline()` 成功结束，且 `predictions`、`nav_daily`、`model_registry` 中至少两项有新增且状态合理
- `run_backtest_pipeline()` 成功结束，且 `predictions` 与 `nav_daily` 成功更新

### 失败处理
- 若 `run_full_pipeline()` 失败，但 `run_backtest_pipeline()` 成功：视为“本轮可发布，但训练入口需列为后续问题”。
- 若两者都失败：列为 **发布阻塞项**，必须反馈，不得隐瞒。
- 禁止为了“让表里有数据”手工伪造结果。

---

## 任务 3：最小环境冻结

### 目标
以极低成本补上“可复现性 B 级”的主要短板，使发布包至少具备一套可抄作业的环境版本记录。

### 必须执行的动作

#### 3.1 生成 Python 依赖冻结文件
在当前可运行环境中执行：
```bash
pip freeze > requirements-lock.txt
```

#### 3.2 写入 Node 版本标记
若项目根目录无 `.nvmrc`，则创建它，内容写入当前验证通过的 Node 主版本，例如：
```bash
18
```
如果实际验证版本不是 18，请以真实版本为准。

#### 3.3 生成版本说明文档
新增 `docs/runtime_versions.md`，至少包含：
- Python 版本（真实值）
- Node 版本（真实值）
- pip freeze 生成时间
- 操作系统信息
- 哪些版本是“推荐版本”，哪些是“已验证版本”

### 必须收集的证据
- `python --version`
- `node --version`
- `pip freeze | head -n 30`
- `requirements-lock.txt` 文件存在证明
- `.nvmrc` 文件内容
- `docs/runtime_versions.md` 文件内容

### 通过标准
- `requirements-lock.txt` 成功生成
- `.nvmrc` 存在且内容明确
- `runtime_versions.md` 写明真实验证环境

### 失败处理
- 若无法生成 `requirements-lock.txt`：记录失败原因，通常应视为环境异常
- 若无 Node：记录前端相关步骤是否仍可完成；若前端构建需要 Node，则列为阻塞项

---

## 任务 4：澄清发布包语义（避免误导用户）

### 目标
明确当前发布包是“源码/研究版发布包”，不是“附带全量数据库的即开即用包”。

### 必须修改的文档
至少修改以下两个位置：
1. `README.md` 顶部
2. `docs/release_manifest.md`

### README 顶部必须新增的说明（可直接照抄）
```markdown
## 发布说明

本项目当前发布物为 **本地研究版源码包（Research Release）**，适用于具备 Python/前端基础的技术用户。

请注意：
- 发布包 **不包含** `data/quant.db`
- 发布包 **不包含** 大体积原始行情与特征缓存
- 用户需要自行生成数据库，或单独获取已有数据库快照
- 因此该发布包不是“解压即用”的完整离线包，而是“源码 + 配置 + 文档 + 前端构建产物”的技术发布包
```

### `release_manifest.md` 必须补充的内容
新增一节：
- 这是“代码发布包”还是“完整运行包”
- 哪些功能解压后立刻可用
- 哪些功能必须先准备数据库后才能使用
- 最少启动路径（例如：安装依赖 → 准备 quant.db → 启动后端/前端）

### 必须收集的证据
- 修改前后的 README 顶部差异
- 修改后的 `docs/release_manifest.md` 关键段落
- 若发布压缩包已生成，重新确认其中不包含 `data/quant.db`

### 通过标准
- README 顶部有显眼说明
- `release_manifest.md` 明确写清包类型和运行前提
- 不再让用户误解为“解压即用”

### 失败处理
- 若 README 不存在：立即创建最小 README 并补充说明
- 若 manifest 与 README 表述冲突：以 README 为准，同时修正 manifest

---

# 三、禁止事项

下级 AI **禁止** 在本轮执行中做以下事情：

1. 禁止开启新的大规模测试矩阵（如多平台、多版本兼容性）
2. 禁止引入新的交互架构重构（CLI/前端/AI 统一动作层等）
3. 禁止为了美观而改前端功能
4. 禁止新增与发布无关的“优化建议”长文
5. 禁止因为某一步失败就改做别的大方向
6. 禁止伪造通过结果、伪造训练产物、伪造日志

本轮唯一目标是：**拿到发布前最后一轮最小硬证据，并把发布表述修正到诚实可交付。**

---

# 四、交付物清单（本轮必须提交）

下级 AI 执行完成后，必须提交以下内容：

## 4.1 文档/文件
- `requirements-lock.txt`
- `.nvmrc`
- `docs/runtime_versions.md`
- 更新后的 `README.md`
- 更新后的 `docs/release_manifest.md`

## 4.2 执行证据报告
新增一份：
- `docs/release_final_execution_report.md`

该报告必须包含以下章节：
1. 任务 1 执行结果
2. 任务 2 执行结果
3. 任务 3 执行结果
4. 任务 4 执行结果
5. 阻塞项
6. 可接受遗留问题
7. 是否建议立即发布

---

# 五、统一反馈模板（必须原样使用）

下级 AI 最终反馈时，不得自由发挥，必须严格使用以下模板。

```markdown
# 发布前最后推进执行报告

## 1. 总结
- 任务 1（最小发布验收子集）: 成功 / 部分成功 / 失败
- 任务 2（训练结果产物）: 成功 / 部分成功 / 失败
- 任务 3（最小环境冻结）: 成功 / 部分成功 / 失败
- 任务 4（澄清发布包语义）: 成功 / 部分成功 / 失败

## 2. 任务 1 结果
### 执行命令
（逐条列出）

### 关键输出
（粘贴真实输出）

### 结论
（是否通过）

## 3. 任务 2 结果
### 执行命令
（逐条列出）

### 训练前状态
（表状态）

### 训练后状态
（表状态）

### 关键输出/指标
（真实输出）

### 结论
（是否通过）

## 4. 任务 3 结果
### 执行命令
（逐条列出）

### 生成文件
- requirements-lock.txt
- .nvmrc
- docs/runtime_versions.md

### 结论
（是否通过）

## 5. 任务 4 结果
### 修改文件
- README.md
- docs/release_manifest.md

### 关键修改内容
（贴出新增段落）

### 结论
（是否通过）

## 6. 阻塞项
- 阻塞项 1:
- 阻塞项 2:

## 7. 可接受遗留问题
- 遗留问题 1:
- 遗留问题 2:

## 8. 发布建议
- [ ] 可以立即发布为 v0.9-beta / Research Release
- [ ] 还需先解决阻塞项后再发布

## 9. 证据文件列表
- docs/release_final_execution_report.md
- requirements-lock.txt
- .nvmrc
- docs/runtime_versions.md
- （其他新增/修改文件）
```

---

# 六、发布判定规则（下级 AI 不得自作主张）

执行完成后，按以下规则给出结论：

## 可立即发布
满足以下条件即可：
- 任务 1 成功或部分成功，但无阻塞项
- 任务 2 至少有最小替代路径成功（`run_backtest_pipeline()` 也可）
- 任务 3 成功
- 任务 4 成功

## 暂缓发布
出现以下任一情况则必须建议暂缓：
- `pytest` 致命失败且影响核心功能
- 前端无法构建
- `predictions` 与 `nav_daily` 都无法生成
- 无法生成 `requirements-lock.txt`
- README/manifest 仍无法说明发布包语义

---

# 七、给下级 AI 的最终要求

请严格执行，不要再写新的战略分析，不要再发散到新功能。  
你本轮的任务不是“把项目做到完美”，而是：

**用最少的动作，拿到可以发布为本地研究版的最后一轮硬证据。**

