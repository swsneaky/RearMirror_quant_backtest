#!/usr/bin/env python3
"""
WORKLOG 归档工具

将超过指定天数的 WORKLOG 记录归档到 WORKLOG_archive/ 目录，
并更新 WORKLOG_index.json 索引。

用法:
    python tools/archive_worklog.py                    # 预览模式 (dry-run)
    python tools/archive_worklog.py --execute          # 执行归档
    python tools/archive_worklog.py --days 30          # 指定归档天数 (默认 30)
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKLOG = ROOT / "WORKLOG.md"
ARCHIVE_DIR = ROOT / "WORKLOG_archive"
INDEX_FILE = ROOT / "WORKLOG_index.json"

# 匹配日志条目头部的正则
# 格式: ## [2026-04-09] | Session B | file_paths_and_output_routing | fix
# 或:   ## 2026-04-08 Session B 增量入库修复 (旧格式)
ENTRY_HEADER_RE = re.compile(
    r"^##\s*(?:\[)?(\d{4}-\d{2}-\d{2})(?:\])?\s*\|?\s*Session\s+[ABCD]",
    re.MULTILINE
)

# 更宽松的日期匹配（兼容旧格式）
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def parse_entries(text: str) -> list[tuple[str, int, int]]:
    """解析 WORKLOG 条目，返回 (日期, 起始位置, 结束位置) 列表"""
    entries = []

    # 找到所有 ## 开头的行
    lines = text.splitlines(keepends=True)
    entry_starts = []

    for i, line in enumerate(lines):
        if line.startswith("## "):
            # 匹配日期
            match = DATE_RE.search(line)
            if match:
                entry_starts.append((match.group(1), i))

    # 计算每个条目的范围
    for idx, (date, line_idx) in enumerate(entry_starts):
        if idx + 1 < len(entry_starts):
            end_idx = entry_starts[idx + 1][1]
        else:
            end_idx = len(lines)
        entries.append((date, line_idx, end_idx))

    return entries


def load_index() -> dict:
    """加载归档索引"""
    if INDEX_FILE.exists():
        return json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    return {"entries": [], "last_archived_date": None}


def save_index(index: dict) -> None:
    """保存归档索引"""
    INDEX_FILE.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def get_quarter(date_str: str) -> str:
    """根据日期确定归档文件名 (如 2026Q1)"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    quarter = (dt.month - 1) // 3 + 1
    return f"{dt.year}Q{quarter}"


def archive_entries(days: int = None, max_entries: int = None, dry_run: bool = True) -> dict:
    """
    归档条目

    Args:
        days: 保留最近多少天的记录（与 max_entries 二选一）
        max_entries: 保留最近多少条记录
        dry_run: 预览模式，不实际修改文件

    Returns:
        统计信息字典
    """
    if not WORKLOG.exists():
        return {"error": "WORKLOG.md 不存在"}

    text = WORKLOG.read_text(encoding="utf-8")
    entries = parse_entries(text)

    if not entries:
        return {"error": "未找到有效的日志条目"}

    # 确定保留策略
    cutoff_date = None
    if max_entries is not None:
        # 按条目数量保留
        to_keep = entries[:max_entries]
        to_archive_all = entries[max_entries:]
    elif days is not None:
        # 按天数保留
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        to_keep = [(d, s, e) for d, s, e in entries if d >= cutoff_date]
        to_archive_all = [(d, s, e) for d, s, e in entries if d < cutoff_date]
    else:
        # 默认保留最近 50 条
        to_keep = entries[:50]
        to_archive_all = entries[50:]

    # 按季度分组归档
    to_archive = {}  # quarter -> [(date, start, end), ...]
    for date, start, end in to_archive_all:
        quarter = get_quarter(date)
        if quarter not in to_archive:
            to_archive[quarter] = []
        to_archive[quarter].append((date, start, end))

    stats = {
        "total_entries": len(entries),
        "keep_count": len(to_keep),
        "archive_count": sum(len(v) for v in to_archive.values()),
        "cutoff_date": cutoff_date if days else f"最近 {len(to_keep)} 条",
        "quarters": list(to_archive.keys()),
        "dry_run": dry_run,
    }

    if dry_run:
        return stats

    # 执行归档
    ARCHIVE_DIR.mkdir(exist_ok=True)
    lines = text.splitlines(keepends=True)

    # 写入归档文件
    for quarter, items in to_archive.items():
        archive_file = ARCHIVE_DIR / f"{quarter}.md"

        # 如果归档文件已存在，追加
        if archive_file.exists():
            existing = archive_file.read_text(encoding="utf-8")
            if not existing.endswith("\n"):
                existing += "\n"
        else:
            existing = "# WORKLOG Archive\n\n"

        # 提取条目内容
        for date, start, end in sorted(items, key=lambda x: x[0]):
            entry_text = "".join(lines[start:end])
            existing += entry_text
            if not entry_text.endswith("\n"):
                existing += "\n"

        archive_file.write_text(existing, encoding="utf-8")

    # 更新索引
    index = load_index()
    for quarter, items in to_archive.items():
        for date, _, _ in items:
            index["entries"].append({
                "date": date,
                "quarter": quarter,
                "file": f"WORKLOG_archive/{quarter}.md",
            })

    # 按日期排序并去重
    index["entries"] = sorted(
        {e["date"]: e for e in index["entries"]}.values(),
        key=lambda x: x["date"],
        reverse=True
    )

    # 记录最后归档日期
    if to_archive:
        all_dates = [d for items in to_archive.values() for d, _, _ in items]
        index["last_archived_date"] = max(all_dates)

    save_index(index)

    # 更新 WORKLOG.md - 只保留最近的条目
    header_lines = []
    in_header = True
    for line in lines:
        if line.startswith("## ") and DATE_RE.search(line):
            in_header = False
            break
        header_lines.append(line)

    # 构建新的 WORKLOG
    new_text = "".join(header_lines)
    if max_entries is not None:
        new_text += f"\n[最近 {max_entries} 条记录。历史记录见 WORKLOG_archive/]\n\n"
    elif days is not None:
        new_text += f"\n[最近 {days} 天记录。历史记录见 WORKLOG_archive/]\n\n"
    else:
        new_text += "\n[最近 50 条记录。历史记录见 WORKLOG_archive/]\n\n"
    new_text += "## 索引\n\n"
    new_text += "| round_id | 归档位置 | 日期 |\n"
    new_text += "|----------|---------|------|\n"

    # 从索引中提取最近归档的条目
    for entry in index["entries"][:10]:
        new_text += f"| {entry['date']} | {entry['file']} | {entry['date']} |\n"

    new_text += "\n---\n\n"

    # 添加保留的条目
    for date, start, end in sorted(to_keep, key=lambda x: x[0], reverse=True):
        new_text += "".join(lines[start:end])

    WORKLOG.write_text(new_text, encoding="utf-8")

    stats["executed"] = True
    return stats


def main():
    parser = argparse.ArgumentParser(description="WORKLOG 归档工具")
    parser.add_argument("--execute", action="store_true", help="执行归档（默认为预览模式）")
    parser.add_argument("--days", type=int, help="保留最近多少天的记录")
    parser.add_argument("--max-entries", type=int, help="保留最近多少条记录（优先于 --days）")
    args = parser.parse_args()

    print(f"{'[预览模式]' if not args.execute else '[执行模式]'}")
    if args.max_entries:
        print(f"保留最近 {args.max_entries} 条记录\n")
    elif args.days:
        print(f"保留最近 {args.days} 天的记录\n")
    else:
        print(f"默认保留最近 50 条记录\n")

    stats = archive_entries(
        days=args.days,
        max_entries=args.max_entries,
        dry_run=not args.execute
    )

    if "error" in stats:
        print(f"错误: {stats['error']}")
        return 1

    print(f"总条目数: {stats['total_entries']}")
    print(f"保留条目: {stats['keep_count']}")
    print(f"归档条目: {stats['archive_count']}")
    print(f"截止日期: {stats['cutoff_date']}")

    if stats.get("quarters"):
        print(f"归档季度: {', '.join(stats['quarters'])}")

    if stats.get("executed"):
        print("\n归档完成!")
        print(f"归档目录: {ARCHIVE_DIR}")
        print(f"索引文件: {INDEX_FILE}")
    else:
        print("\n[提示] 使用 --execute 参数执行实际归档")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
