"""
任务管理 API

端点:
  POST /api/tasks                      -- 创建新任务 (数据更新/中性化计算等)
  GET  /api/tasks                      -- 列出任务
  GET  /api/tasks/{task_id}            -- 获取任务详情 (含进度)
  POST /api/tasks/{task_id}/cancel     -- 取消任务
  POST /api/tasks/{task_id}/retry      -- 重试失败任务
  POST /api/tasks/{task_id}/kill-cleanup -- 终止进程并清理文件
  POST /api/tasks/{task_id}/pause      -- 暂停任务
  POST /api/tasks/{task_id}/resume     -- 恢复任务
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.tasking.manager import TaskManager
from src.tasking.models import TaskRecord, TaskStatus
from src.tasking.store import TaskStore

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


# ================================================================
# 响应模型
# ================================================================
class TaskCreateRequest(BaseModel):
    """创建任务请求"""
    task_type: str  # "data_update" | "feature_compute" | "backtest" | "full_pipeline"
    steps: list[str] = []
    notes: str = ""

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "task_type": "data_update",
                "steps": ["download", "etl"],
                "notes": "手动触发的数据更新"
            }]
        }
    }


class TaskResponse(BaseModel):
    """任务响应"""
    task_id: str
    status: str  # pending | running | succeeded | failed | cancelled
    progress_pct: int
    progress_message: str
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error_message: Optional[str] = None
    steps: str
    model_name: str
    universe_name: str
    submit_source: str


class TaskListResponse(BaseModel):
    """任务列表响应"""
    tasks: list[TaskResponse]
    total: int


class TaskActionResponse(BaseModel):
    """任务操作响应"""
    success: bool
    message: str
    task_id: str


# ================================================================
# 辅助函数
# ================================================================
def _task_record_to_response(record: TaskRecord) -> TaskResponse:
    """将 TaskRecord 转换为 TaskResponse"""
    return TaskResponse(
        task_id=record.task_id,
        status=record.status.value,
        progress_pct=record.progress_pct,
        progress_message=record.progress_message,
        created_at=record.created_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
        error_message=record.error_message,
        steps=record.steps,
        model_name=record.model_name,
        universe_name=record.universe_name,
        submit_source=record.submit_source,
    )


def _get_manager() -> TaskManager:
    """获取 TaskManager 实例"""
    store = TaskStore()
    return TaskManager(store=store)


# ================================================================
# 端点实现
# ================================================================
@router.post("", response_model=TaskActionResponse)
async def create_task(request: TaskCreateRequest):
    """
    创建新任务

    task_type 支持的类型:
    - data_update: 数据更新 (下载 + ETL)
    - feature_compute: 特征计算
    - backtest: 回测执行
    - full_pipeline: 完整流程
    """
    # 映射 task_type 到 steps
    task_type_to_steps = {
        "data_update": ["download", "etl"],
        "feature_compute": ["raw_feature", "neutralize"],
        "backtest": ["backtest"],
        "full_pipeline": ["download", "etl", "raw_feature", "neutralize", "backtest"],
    }

    if request.task_type not in task_type_to_steps:
        raise HTTPException(
            status_code=400,
            detail=f"无效的 task_type: {request.task_type}。支持: {list(task_type_to_steps.keys())}"
        )

    # 使用请求中的 steps，如果为空则使用默认映射
    steps = request.steps if request.steps else task_type_to_steps[request.task_type]

    manager = _get_manager()
    try:
        record = manager.submit(
            steps=steps,
            notes=request.notes,
            submit_source="ui",
        )
        return TaskActionResponse(
            success=True,
            message=f"任务 {record.task_id} 创建成功",
            task_id=record.task_id,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建任务失败: {str(e)}")


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    status: Optional[str] = None,
    limit: int = 50,
):
    """
    列出任务

    参数:
    - status: 按状态过滤 (pending | running | succeeded | failed | cancelled)
    - limit: 返回数量限制
    """
    manager = _get_manager()

    task_status = None
    if status:
        try:
            task_status = TaskStatus(status)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"无效的状态: {status}。支持: pending, running, succeeded, failed, cancelled"
            )

    records = manager.list_tasks(status=task_status, limit=limit)
    tasks = [_task_record_to_response(r) for r in records]

    return TaskListResponse(
        tasks=tasks,
        total=len(tasks),
    )


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str):
    """获取任务详情 (含进度)"""
    manager = _get_manager()
    record = manager.get(task_id)

    if record is None:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")

    return _task_record_to_response(record)


@router.post("/{task_id}/cancel", response_model=TaskActionResponse)
async def cancel_task(task_id: str):
    """取消任务"""
    manager = _get_manager()

    try:
        success = manager.cancel(task_id)
        return TaskActionResponse(
            success=success,
            message=f"任务 {task_id} 已取消",
            task_id=task_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{task_id}/retry", response_model=TaskActionResponse)
async def retry_task(task_id: str):
    """重试失败任务"""
    manager = _get_manager()

    try:
        new_record = manager.retry(task_id, submit_source="ui")
        return TaskActionResponse(
            success=True,
            message=f"已创建新任务 {new_record.task_id} 重试 {task_id}",
            task_id=new_record.task_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{task_id}/kill-cleanup", response_model=TaskActionResponse)
async def kill_and_cleanup(task_id: str):
    """
    终止任务进程并清理残余文件

    1. 杀死任务进程 (通过 PID)
    2. 等待进程释放文件句柄
    3. 删除任务输出目录
    4. 更新任务状态为 cancelled
    """
    import os
    import signal
    import shutil
    import time

    store = TaskStore()
    record = store.get(task_id)

    if record is None:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")

    messages = []

    # 1. 杀进程
    if record.pid:
        try:
            os.kill(record.pid, signal.SIGTERM)
            messages.append(f"已终止进程 PID={record.pid}")
            # 等待进程释放文件句柄
            time.sleep(0.5)
        except ProcessLookupError:
            messages.append(f"进程 PID={record.pid} 已不存在")
        except Exception as e:
            messages.append(f"终止进程失败: {e}")

    # 2. 删除输出目录
    if record.output_dir and os.path.exists(record.output_dir):
        try:
            shutil.rmtree(record.output_dir)
            messages.append(f"已删除目录 {record.output_dir}")
        except Exception as e:
            messages.append(f"删除目录失败: {e}")

    # 3. 更新状态
    store.update_status(
        task_id, TaskStatus.CANCELLED,
        finished_at=datetime.now().isoformat(),
        error_message="用户强制终止",
    )
    messages.append("任务状态已更新为 cancelled")

    return TaskActionResponse(
        success=True,
        message=" | ".join(messages),
        task_id=task_id,
    )


@router.post("/{task_id}/pause", response_model=TaskActionResponse)
async def pause_task(task_id: str):
    """
    暂停任务

    创建 .pause 标记文件，任务在安全检查点会检测并暂停
    """
    store = TaskStore()
    record = store.get(task_id)

    if record is None:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")

    if record.status != TaskStatus.RUNNING:
        raise HTTPException(status_code=400, detail=f"只能暂停 running 状态的任务，当前: {record.status.value}")

    # 创建暂停标记
    if record.output_dir:
        pause_flag = os.path.join(record.output_dir, ".pause")
        os.makedirs(os.path.dirname(pause_flag) or ".", exist_ok=True)
        with open(pause_flag, "w") as f:
            f.write(datetime.now().isoformat())

    # 更新状态
    store.update_status(task_id, TaskStatus.PAUSED)

    return TaskActionResponse(
        success=True,
        message=f"任务 {task_id} 已标记为暂停",
        task_id=task_id,
    )


@router.post("/{task_id}/resume", response_model=TaskActionResponse)
async def resume_task(task_id: str):
    """
    恢复暂停的任务

    删除 .pause 标记文件，更新状态为 running
    """
    store = TaskStore()
    record = store.get(task_id)

    if record is None:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")

    if record.status != TaskStatus.PAUSED:
        raise HTTPException(status_code=400, detail=f"只能恢复 paused 状态的任务，当前: {record.status.value}")

    # 删除暂停标记
    if record.output_dir:
        pause_flag = os.path.join(record.output_dir, ".pause")
        if os.path.exists(pause_flag):
            os.remove(pause_flag)

    # 更新状态
    store.update_status(task_id, TaskStatus.RUNNING)

    return TaskActionResponse(
        success=True,
        message=f"任务 {task_id} 已恢复",
        task_id=task_id,
    )
