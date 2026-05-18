from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
HANDOFF = ROOT / "HANDOFF.md"
WORKLOG = ROOT / "WORKLOG.md"
AI_CONTEXT = ROOT / "AI_CONTEXT.md"
PROGRESS = ROOT / "PROGRESS.md"
RULEBOOKS = {
    ROOT / "docs" / "rulebooks" / "collaboration_rulebook.md": [
        "# Collaboration Rulebook",
        "## 1. Handoff Payload Standard",
        "## 2. Work Log Protocol",
    ],
    ROOT / "docs" / "rulebooks" / "project_baseline.md": [
        "# Project Baseline",
        "## 4. Data Layer Hierarchy",
        "## 8. Workflow Gates",
    ],
    ROOT / "docs" / "rulebooks" / "business_invariants.md": [
        "# Business Invariants",
        "## 2. Cross-Section Discipline",
    ],
    ROOT / "docs" / "rulebooks" / "engineering_constraints.md": [
        "# Engineering Constraints",
        "## 5. File Lifecycle & Cleanup Governance",
        "### 5.7 Three Core Files",
    ],
    ROOT / "docs" / "rulebooks" / "result_reporting.md": [
        "# Result Reporting",
        "## 1. Decision Brief Requirement",
        "## 2. Required Artifacts",
    ],
    ROOT / "docs" / "rulebooks" / "capability_rollout.md": [
        "# Capability Rollout",
        "## 1. Decision Point Requirement",
        "## 2. Allowed Capability Slices",
    ],
    ROOT / "docs" / "rulebooks" / "research_iteration_policy.md": [
        "# Research Iteration Policy",
        "## 1. Asset Status Rule",
        "## 2. Iteration Method Rule",
    ],
    ROOT / "docs" / "rulebooks" / "subagent_protocol.md": [
        "# Subagent Protocol",
        "## 1. Architecture Principles",
        "## 2. Subagent Types",
    ],
}

VALID_TAGS = {
    "[WAITING_FOR_A_ARCHITECT]",
    "[WAITING_FOR_B_CODER]",
    "[WAITING_FOR_D_QA]",
    "[WAITING_FOR_C_AUDITOR]",
}

VALID_AXES = {
    "business_mainline",
    "governance_and_operationalization",
}

VALID_ROLES = {"Session A", "Session B", "Session C", "Session D"}
VALID_ACTION_TYPES = {"正常流转", "故障回退", "阻塞待补证据"}

HANDOFF_LABELS = [
    "动作类型:",
    "所属轴线:",
    "当前流程:",
    "关联业务主线:",
    "最小读取范围:",
    "结论:",
    "必做项:",
    "证据:",
    "完成标准:",
    "非目标:",
    "发送方:",
    "接收方:",
]


def fail(errors: list[str], message: str) -> None:
    errors.append(message)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _line_value(lines: list[str], label: str) -> str:
    idx = lines.index(label)
    for candidate in lines[idx + 1 :]:
        stripped = candidate.strip()
        if stripped:
            return stripped
    return ""


def validate_handoff() -> list[str]:
    errors: list[str] = []
    text = _read_text(HANDOFF)
    lines = text.splitlines()

    if not lines:
        return ["HANDOFF.md is empty"]

    tag = lines[0].strip()
    if tag not in VALID_TAGS:
        fail(errors, f"HANDOFF invalid state tag: {tag!r}")

    positions: dict[str, int] = {}
    for label in HANDOFF_LABELS:
        try:
            positions[label] = lines.index(label)
        except ValueError:
            fail(errors, f"HANDOFF missing label: {label}")

    if not errors:
        ordered = [positions[label] for label in HANDOFF_LABELS]
        if ordered != sorted(ordered):
            fail(errors, "HANDOFF labels are out of required order")

    if "所属轴线:" in positions:
        axis = _line_value(lines, "所属轴线:")
        if axis not in VALID_AXES:
            fail(errors, f"HANDOFF invalid 所属轴线: {axis!r}")

    if "动作类型:" in positions:
        action_type = _line_value(lines, "动作类型:")
        if action_type not in VALID_ACTION_TYPES:
            fail(errors, f"HANDOFF invalid 动作类型: {action_type!r}")

    if "当前流程:" in positions:
        flow = _line_value(lines, "当前流程:")
        if not flow:
            fail(errors, "HANDOFF 当前流程 is empty")

    if "关联业务主线:" in positions:
        related = _line_value(lines, "关联业务主线:")
        if not related:
            fail(errors, "HANDOFF 关联业务主线 is empty")

    sender = ""
    receiver = ""
    if "发送方:" in positions:
        sender = _line_value(lines, "发送方:")
        if sender not in VALID_ROLES:
            fail(errors, f"HANDOFF invalid 发送方: {sender!r}")

    if "接收方:" in positions:
        receiver = _line_value(lines, "接收方:")
        if receiver not in VALID_ROLES:
            fail(errors, f"HANDOFF invalid 接收方: {receiver!r}")

    # 新增：发送方 != 接收方
    # 例外：Session A 收口裁定后持有球权 (A->A) 是合法闭合模式
    if sender and receiver and sender == receiver and sender != "Session A":
        fail(errors, f"HANDOFF 发送方和接收方不能相同: {sender}")

    # 新增：状态标签与接收方匹配
    status_receiver_map = {
        "[WAITING_FOR_A_ARCHITECT]": "Session A",
        "[WAITING_FOR_B_CODER]": "Session B",
        "[WAITING_FOR_D_QA]": "Session D",
        "[WAITING_FOR_C_AUDITOR]": "Session C",
    }
    if tag in status_receiver_map:
        expected = status_receiver_map[tag]
        if receiver and receiver != expected:
            fail(errors, f"HANDOFF 状态 {tag} 应对应接收方 {expected}，实际为 {receiver}")

    # 新增：动作类型与流转方向合理性
    action_type = ""
    if "动作类型:" in positions:
        action_type = _line_value(lines, "动作类型:")

    if action_type == "故障回退" and sender and receiver:
        # 回退时，接收方应该是上游角色
        upstream = {
            "Session D": ["Session B", "Session C", "Session A"],
            "Session C": ["Session B", "Session A"],
            "Session B": ["Session A"],
            "Session A": [],  # A 是顶层，只能回退给自己（重新裁决）
        }
        if sender in upstream and receiver not in upstream[sender]:
            # A 回退给自己是允许的（重新裁决）
            if not (sender == "Session A" and receiver == "Session A"):
                fail(errors, f"故障回退时 {sender} 应回退给上游角色，而非 {receiver}")

    if "最小读取范围:" in positions:
        start = positions["最小读取范围:"] + 1
        end = positions.get("结论:", len(lines))
        block = lines[start:end]
        numbered = [line for line in block if re.match(r"^\d+\.\s", line)]
        if not numbered:
            fail(errors, "HANDOFF 最小读取范围 has no numbered items")
        if len(numbered) < 3:
            fail(errors, "HANDOFF 最小读取范围 should include WORKLOG / rules / code entry categories")
        if not any("AI_CONTEXT.md" in line for line in block):
            fail(errors, "HANDOFF 最小读取范围 must include AI_CONTEXT.md")
        if not any("WORKLOG.md" in line for line in block):
            fail(errors, "HANDOFF 最小读取范围 must include WORKLOG.md")

    if "结论:" in positions:
        conclusion = _line_value(lines, "结论:")
        conclusion_match = re.match(r"^(正常流转|故障回退|阻塞待补证据)：", conclusion)
        if not conclusion_match:
            fail(errors, "HANDOFF 结论 must start with a valid action type")
        elif action_type in VALID_ACTION_TYPES and conclusion_match.group(1) != action_type:
            fail(errors, "HANDOFF 动作类型 must match the 结论 prefix")

    return errors


def validate_worklog() -> list[str]:
    errors: list[str] = []
    text = _read_text(WORKLOG)
    lines = text.splitlines()
    if not lines or lines[0].strip() != "# WORKLOG":
        fail(errors, "WORKLOG must start with '# WORKLOG'")
        return errors

    if len(lines) < 4:
        fail(errors, "WORKLOG header is too short")
        return errors

    if "先读 AI_CONTEXT.md" not in text or "再读 HANDOFF.md" not in text:
        fail(errors, "WORKLOG header should remind readers to read AI_CONTEXT first and HANDOFF second")

    if not re.search(r"^##\s\[.+\]\s\|\sSession [ABCD]\s\|\s.+\|\s.+$", text, re.M):
        fail(errors, "WORKLOG has no valid log entry header")

    # 新增：文件大小警告
    size_kb = WORKLOG.stat().st_size / 1024
    if size_kb > 100:
        fail(errors, f"WORKLOG.md 过大 ({size_kb:.1f}KB)，建议运行 python tools/archive_worklog.py 归档")
    elif size_kb > 50:
        # 警告但不报错
        print(f"[WARN] WORKLOG.md 较大 ({size_kb:.1f}KB)，建议近期归档")

    return errors


def validate_ai_context() -> list[str]:
    errors: list[str] = []
    text = _read_text(AI_CONTEXT)
    if "新 session 或冷启动时，默认先读 `AI_CONTEXT.md` 的主宪章部分" not in text:
        fail(errors, "AI_CONTEXT missing constitution-first cold-start rule")
    if "随后再读 `HANDOFF.md`" not in text:
        fail(errors, "AI_CONTEXT missing HANDOFF-second cold-start rule")
    if not re.search(r"最小读取范围中.*AI_CONTEXT\.md.*不得缺席", text):
        fail(errors, "AI_CONTEXT missing rule that HANDOFF minimum reading must include AI_CONTEXT")
    if "## 1.5 Rulebook Map" not in text:
        fail(errors, "AI_CONTEXT missing rulebook map section")
    if "docs/rulebooks/collaboration_rulebook.md" not in text:
        fail(errors, "AI_CONTEXT missing collaboration rulebook routing")
    if "docs/rulebooks/engineering_constraints.md" not in text:
        fail(errors, "AI_CONTEXT missing engineering rulebook routing")
    if "docs/rulebooks/result_reporting.md" not in text:
        fail(errors, "AI_CONTEXT missing result reporting rulebook routing")
    if "docs/rulebooks/capability_rollout.md" not in text:
        fail(errors, "AI_CONTEXT missing capability rollout rulebook routing")
    if "docs/rulebooks/research_iteration_policy.md" not in text:
        fail(errors, "AI_CONTEXT missing research iteration policy rulebook routing")
    return errors


def validate_rulebooks() -> list[str]:
    errors: list[str] = []
    for path, phrases in RULEBOOKS.items():
        if not path.exists():
            fail(errors, f"Rulebook missing: {path.relative_to(ROOT)}")
            continue
        text = _read_text(path)
        for phrase in phrases:
            if phrase not in text:
                fail(errors, f"Rulebook missing required phrase in {path.relative_to(ROOT)}: {phrase}")
    return errors


def validate_progress() -> list[str]:
    """校验 PROGRESS.md 阶段进度文件"""
    errors: list[str] = []

    if not PROGRESS.exists():
        fail(errors, "PROGRESS.md not found")
        return errors

    text = _read_text(PROGRESS)
    lines = text.splitlines()

    # 检查标题
    if not lines or not lines[0].strip().startswith("# RearMirror"):
        fail(errors, "PROGRESS.md must start with '# RearMirror' title")

    # 检查业务阶段表
    if "## 业务主线阶段进度" not in text and "## 业务阶段" not in text:
        fail(errors, "PROGRESS.md missing business stage progress section")

    # 检查是否有阶段表格
    if not re.search(r"\|\s*阶段\s*\|\s*状态\s*\|", text):
        fail(errors, "PROGRESS.md missing stage status table")

    # 检查是否有日期记录
    if not re.search(r"##\s*\d{4}-\d{2}-\d{2}", text):
        fail(errors, "PROGRESS.md missing dated progress entries")

    return errors


def main() -> int:
    errors = [
        *validate_handoff(),
        *validate_worklog(),
        *validate_ai_context(),
        *validate_progress(),
        *validate_rulebooks(),
    ]
    if errors:
        print("THREE-FILE VALIDATION FAILED")
        for item in errors:
            print(f"- {item}")
        return 1

    print("THREE-FILE VALIDATION OK")
    print(f"- HANDOFF: {HANDOFF}")
    print(f"- WORKLOG: {WORKLOG}")
    print(f"- AI_CONTEXT: {AI_CONTEXT}")
    print(f"- PROGRESS: {PROGRESS}")
    for path in RULEBOOKS:
        print(f"- RULEBOOK: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
