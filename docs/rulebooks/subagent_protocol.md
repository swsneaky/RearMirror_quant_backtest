# Subagent Protocol (子 Agent 调度协议)

本分册定义 RearMirror 项目中主 Agent 与 Subagent 的协作方式。

---

## 1. Architecture Principles (架构原则)

### 1.1 主 Agent 职责

- **保持上下文**：规则、状态、历史记录
- **读取 HANDOFF**：判断当前角色
- **调度决策**：决定启动哪个 Subagent
- **更新状态**：修改 HANDOFF.md、追加 WORKLOG.md
- **扮演 Session A**：A 的裁定工作由主 Agent 直接执行

### 1.2 Subagent 职责

- **执行具体任务**：运行测试、代码修改、审计检查
- **返回结果**：findings、evidence、建议
- **无状态**：执行完即销毁，不保持上下文
- **不更新状态文件**：HANDOFF/WORKLOG 由主 Agent 更新

---

## 2. Subagent Types (子Agent类型)

| 类型 | 用途 | 启动条件 |
|------|------|----------|
| `session_d_verify` | 运行测试、验证、收集证据 | 当前角色为 D 且需要执行验证 |
| `session_b_impl` | 代码修改、功能实现 | 当前角色为 B 且需要写代码 |
| `session_c_audit` | 审计检查、一致性验证 | 当前角色为 C 且需要具体审计 |
| `explore` | 搜索文件、分析代码 | 需要探索代码库时 |

---

## 3. Prompt 模板

### 3.1 Session D 验证任务

```
你是 RearMirror 项目的验证执行者。

任务: {具体验证任务}

输入:
- 任务描述: {从 HANDOFF 提取}
- 完成标准: {从 HANDOFF 提取}

执行步骤:
1. {步骤1}
2. {步骤2}
...

返回格式:
{
  "findings": ["发现1", "发现2"],
  "evidence": ["证据1", "证据2"],
  "decision": "passed / failed / blocked",
  "next_suggestion": "建议下一步"
}

禁止:
- 不要修改 HANDOFF.md
- 不要宣布阶段收口
```

### 3.2 Session B 实现任务

```
你是 RearMirror 项目的开发者。

任务: {具体实现任务}

输入:
- 需求描述: {从 HANDOFF 提取}
- 约束条件: {从 AI_CONTEXT 提取}

工作目录: E:/quant/RearMirror

执行步骤:
1. 阅读相关代码
2. 实现修改
3. 运行基础测试验证

返回格式:
{
  "modified_files": ["文件1", "文件2"],
  "changes_summary": "修改摘要",
  "test_result": "passed / failed",
  "issues": ["问题1"] 或 []
}

禁止:
- 不要修改 HANDOFF.md / WORKLOG.md
- 不要修改长期规则文件
```

### 3.3 Session C 审计任务

```
你是 RearMirror 项目的审计者。

任务: {具体审计任务}

输入:
- 审计对象: {文件/产物}
- 审计标准: {从 rulebook 提取}

执行步骤:
1. 读取审计对象
2. 对照标准检查
3. 记录发现

返回格式:
{
  "checklist": [
    {"item": "检查项1", "status": "pass/fail", "note": "备注"},
    ...
  ],
  "overall": "passed / failed / passed-with-conditions",
  "issues": ["问题1"] 或 [],
  "recommendation": "建议"
}

禁止:
- 不要修改任何文件
```

---

## 4. 主 Agent 工作流程

```
1. 用户触发: "继续" / "执行任务"

2. 主 Agent 读取 HANDOFF.md 第一行

3. 判断当前角色:
   - [WAITING_FOR_A_ARCHITECT] → 主 Agent 直接执行 A 的裁定
   - [WAITING_FOR_B_CODER] → 启动 Subagent B 执行实现
   - [WAITING_FOR_D_QA] → 启动 Subagent D 执行验证
   - [WAITING_FOR_C_AUDITOR] → 启动 Subagent C 执行审计

4. 等待 Subagent 返回结果

5. 根据结果更新 HANDOFF.md + WORKLOG.md

6. 运行 validate_three_files.py

7. 等待用户下一次触发
```

---

## 5. Subagent 启动方式

### 5.1 前台运行（默认）

```python
Agent(
    description="Session D 验证",
    prompt=prompt_content,
    subagent_type="general-purpose"
)
```

### 5.2 后台运行（耗时任务）

```python
Agent(
    description="完整回测",
    prompt=prompt_content,
    run_in_background=True
)
```

### 5.3 并行启动

```python
# 在一个消息中同时启动多个 Agent
Agent(description="任务1", prompt=...)
Agent(description="任务2", prompt=...)
```

---

## 6. 与 `/loop` 的配合

可选：使用 `/loop` 定期检查 HANDOFF 并自动推进。

```
/loop 1m 读取 HANDOFF.md，根据当前状态执行对应任务
```

主 Agent 保持上下文，Subagent 执行具体工作。
