#!/usr/bin/env python
"""
RearMirror 任务 CLI -- submit / list / show / retry / cancel / worker

用法:
    python task_cli.py submit --model xgboost --top-k 100 --train-window 500
    python task_cli.py submit --profile configs/profiles/zz500_xgb_baseline.yaml
    python task_cli.py list
    python task_cli.py list --status failed
    python task_cli.py show <task_id>
    python task_cli.py retry <task_id>
    python task_cli.py cancel <task_id>
    python task_cli.py worker                # 启动后台执行器
"""
from __future__ import annotations

import argparse
import json
import os
import time

from src.tasking import TaskManager, TaskStore, TaskStatus
from src.tasking.executor import TaskExecutor


def cmd_submit(args):
    mgr = TaskManager()
    ui_overrides = {}
    if args.model:
        ui_overrides.setdefault("model", {})["active"] = args.model
    if args.top_k:
        ui_overrides.setdefault("backtest", {})["top_k"] = args.top_k
    if args.train_window:
        ui_overrides.setdefault("backtest", {})["train_window"] = args.train_window
    if args.step:
        ui_overrides.setdefault("backtest", {})["test_step"] = args.step
    if args.gap:
        ui_overrides.setdefault("backtest", {})["gap"] = args.gap

    steps = [s.strip() for s in args.steps.split(",")]

    task = mgr.submit(
        profile_path=args.profile or None,
        ui_overrides=ui_overrides if ui_overrides else None,
        submit_source="cli",
        steps=steps,
    )
    print(f"[OK] 任务已提交: {task.task_id}")
    print(f"   输出目录: {task.output_dir}")
    print(f"   模型: {task.model_name} | Top K: {task.top_k} | 训练窗口: {task.train_window}")


def cmd_list(args):
    store = TaskStore()
    status = TaskStatus(args.status) if args.status else None
    tasks = store.list_tasks(status=status, limit=args.limit)
    if not tasks:
        print("暂无任务。")
        return

    print(f"{'状态':<12} {'任务ID':<36} {'模型':<12} {'Top K':>6} "
          f"{'创建时间':<20} {'错误':<30}")
    print("-" * 120)
    for t in tasks:
        err = (t.error_message or "")[:28]
        created = (t.created_at or "")[:19]
        print(f"{t.status.value:<12} {t.task_id:<36} {t.model_name:<12} "
              f"{t.top_k:>6} {created:<20} {err:<30}")


def cmd_show(args):
    store = TaskStore()
    task = store.get(args.task_id)
    if task is None:
        print(f"[FAIL] 任务 {args.task_id} 不存在")
        return

    d = task.to_dict()
    for k, v in d.items():
        print(f"  {k:<25}: {v}")

    metrics_path = os.path.join(task.output_dir or "", "results", "metrics.json")
    if os.path.exists(metrics_path):
        print("\n[STAT] 业绩指标:")
        with open(metrics_path, "r", encoding="utf-8") as f:
            metrics = json.load(f)
        for k, v in metrics.items():
            if isinstance(v, float):
                print(f"  {k:<25}: {v:.4f}")
            else:
                print(f"  {k:<25}: {v}")


def cmd_retry(args):
    mgr = TaskManager()
    new_task = mgr.retry(args.task_id, submit_source="cli")
    print(f"[OK] 重试任务已提交: {new_task.task_id} (重试自 {args.task_id})")


def cmd_cancel(args):
    mgr = TaskManager()
    mgr.cancel(args.task_id)
    print(f"[OK] 已取消: {args.task_id}")


def cmd_worker(args):
    store = TaskStore()
    exe = TaskExecutor(store=store, max_workers=args.workers)
    exe.start()
    print(f"[RUN] Worker 已启动 (max_workers={args.workers})，按 Ctrl+C 停止...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[STOP] 正在关闭...")
        exe.stop()


def main():
    parser = argparse.ArgumentParser(description="RearMirror 多任务 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # submit
    p_submit = sub.add_parser("submit", help="提交回测任务")
    p_submit.add_argument("--profile", default=None, help="Profile YAML 路径")
    p_submit.add_argument("--model", default=None, help="模型名称")
    p_submit.add_argument("--top-k", type=int, default=None)
    p_submit.add_argument("--train-window", type=int, default=None)
    p_submit.add_argument("--step", type=int, default=None)
    p_submit.add_argument("--gap", type=int, default=None)
    p_submit.add_argument("--steps", default="raw_feature,neutralize,backtest",
                          help="执行步骤 (逗号分隔: download,etl,raw_feature,neutralize,feature,backtest,factor_analysis)")

    # list
    p_list = sub.add_parser("list", help="列出任务")
    p_list.add_argument("--status", default=None, help="按状态筛选")
    p_list.add_argument("--limit", type=int, default=50)

    # show
    p_show = sub.add_parser("show", help="查看任务详情")
    p_show.add_argument("task_id", help="任务 ID")

    # retry
    p_retry = sub.add_parser("retry", help="重试失败任务")
    p_retry.add_argument("task_id", help="任务 ID")

    # cancel
    p_cancel = sub.add_parser("cancel", help="取消任务")
    p_cancel.add_argument("task_id", help="任务 ID")

    # worker
    p_worker = sub.add_parser("worker", help="启动后台执行器")
    p_worker.add_argument("--workers", type=int, default=2, help="最大并发数")

    args = parser.parse_args()
    {
        "submit": cmd_submit,
        "list": cmd_list,
        "show": cmd_show,
        "retry": cmd_retry,
        "cancel": cmd_cancel,
        "worker": cmd_worker,
    }[args.command](args)


if __name__ == "__main__":
    main()
