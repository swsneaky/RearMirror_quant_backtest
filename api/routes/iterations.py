"""
迭代结果 API

端点:
  GET  /api/iterations              -- 获取迭代列表
  GET  /api/iterations/{id}         -- 获取迭代详情
  POST /api/iterations              -- 创建迭代并生成 MD
  GET  /api/iterations/{id}/brief   -- 获取 Markdown 简报
  GET  /api/iterations/{id}/artifacts -- 获取产物清单
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pathlib import Path
import json
from datetime import datetime
from typing import Optional

from api.schemas.iteration import (
    IterationCreateRequest,
    IterationCreateResponse,
    IterationListResponse,
    IterationListItem,
    IterationDetailResponse,
    ArtifactsResponse,
)
from src.reporting.brief_generator import generate_iteration_brief

router = APIRouter(prefix="/api/iterations", tags=["iterations"])

ITERATIONS_DIR = Path("data/results/iterations")


def _get_iteration_dir(iteration_id: str) -> Path:
    """获取迭代目录路径"""
    return ITERATIONS_DIR / iteration_id


def _get_summary_path(iteration_id: str) -> Path:
    """获取迭代摘要 JSON 路径"""
    return _get_iteration_dir(iteration_id) / "iteration_result_summary.json"


def _get_brief_path(iteration_id: str) -> Path:
    """获取迭代简报 MD 路径"""
    return _get_iteration_dir(iteration_id) / "iteration_result_brief.md"


def _load_summary(iteration_id: str) -> Optional[dict]:
    """加载迭代摘要 JSON"""
    summary_path = _get_summary_path(iteration_id)
    if not summary_path.exists():
        return None
    try:
        with open(summary_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _generate_iteration_id() -> str:
    """生成新的迭代 ID"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"iteration_{timestamp}"


@router.get("", response_model=IterationListResponse)
async def list_iterations():
    """
    获取迭代列表

    扫描 iterations 目录，返回所有迭代摘要
    """
    iterations = []

    if not ITERATIONS_DIR.exists():
        return IterationListResponse(iterations=[], total=0)

    for iter_dir in sorted(ITERATIONS_DIR.iterdir(), reverse=True):
        if not iter_dir.is_dir():
            continue

        iteration_id = iter_dir.name
        summary = _load_summary(iteration_id)

        if summary:
            iterations.append(IterationListItem(
                iteration_id=summary.get("iteration_id", iteration_id),
                date=summary.get("date", ""),
                stage=summary.get("stage", ""),
                conclusion=summary.get("conclusion", ""),
                recommendation=summary.get("recommendation", ""),
            ))
        else:
            # 如果没有 summary.json，使用目录信息
            iterations.append(IterationListItem(
                iteration_id=iteration_id,
                date="",
                stage="unknown",
                conclusion="无摘要数据",
                recommendation="",
            ))

    return IterationListResponse(
        iterations=iterations,
        total=len(iterations)
    )


@router.get("/{iteration_id}", response_model=IterationDetailResponse)
async def get_iteration(iteration_id: str):
    """
    获取迭代详情

    返回完整的迭代摘要信息
    """
    summary = _load_summary(iteration_id)

    if not summary:
        raise HTTPException(status_code=404, detail=f"Iteration '{iteration_id}' not found")

    # 尝试加载 Markdown 简报
    brief_path = _get_brief_path(iteration_id)
    brief_content = None
    if brief_path.exists():
        try:
            with open(brief_path, "r", encoding="utf-8") as f:
                brief_content = f.read()
        except Exception:
            pass

    return IterationDetailResponse(
        iteration_id=summary.get("iteration_id", iteration_id),
        date=summary.get("date", ""),
        stage=summary.get("stage", ""),
        feature_set_id=summary.get("feature_set_id"),
        label_set_id=summary.get("label_set_id"),
        runtime_mode=summary.get("runtime_mode"),
        conclusion=summary.get("conclusion", ""),
        metrics=summary.get("metrics", {}),
        data_scale=summary.get("data_scale", {}),
        recommendation=summary.get("recommendation", ""),
        recommendation_reason=summary.get("recommendation_reason"),
        premises=summary.get("premises", []),
        artifacts=summary.get("artifacts", {}),
        hpo_study_name=summary.get("hpo_study_name"),
        brief_content=brief_content,
    )


@router.post("", response_model=IterationCreateResponse)
async def create_iteration(request: IterationCreateRequest):
    """
    创建迭代并生成 MD 简报

    保存 JSON 摘要和 Markdown 简报
    """
    # 生成或使用提供的 iteration_id
    iteration_id = request.iteration_id or _generate_iteration_id()

    # 准备摘要数据
    summary_data = {
        "iteration_id": iteration_id,
        "date": request.date or datetime.now().strftime("%Y-%m-%d"),
        "stage": request.stage,
        "feature_set_id": request.feature_set_id,
        "label_set_id": request.label_set_id,
        "runtime_mode": request.runtime_mode,
        "conclusion": request.conclusion,
        "metrics": request.metrics or {},
        "data_scale": request.data_scale or {},
        "recommendation": request.recommendation,
        "recommendation_reason": request.recommendation_reason,
        "premises": request.premises or [],
        "artifacts": request.artifacts or {},
        "hpo_study_name": request.hpo_study_name,
    }

    # 创建迭代目录
    iter_dir = _get_iteration_dir(iteration_id)
    iter_dir.mkdir(parents=True, exist_ok=True)

    # 保存 JSON 摘要
    json_path = _get_summary_path(iteration_id)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, ensure_ascii=False, indent=2)

    # 生成并保存 Markdown 简报
    brief_content = generate_iteration_brief(summary_data)
    brief_path = _get_brief_path(iteration_id)
    with open(brief_path, "w", encoding="utf-8") as f:
        f.write(brief_content)

    return IterationCreateResponse(
        iteration_id=iteration_id,
        json_path=str(json_path),
        brief_path=str(brief_path),
        message=f"Iteration '{iteration_id}' created successfully",
    )


@router.get("/{iteration_id}/brief")
async def get_iteration_brief(iteration_id: str):
    """
    获取迭代 Markdown 简报

    返回 iteration_result_brief.md 内容
    """
    brief_path = _get_brief_path(iteration_id)

    if not brief_path.exists():
        # 尝试从 summary 重新生成
        summary = _load_summary(iteration_id)
        if not summary:
            raise HTTPException(status_code=404, detail=f"Iteration '{iteration_id}' not found")

        brief_content = generate_iteration_brief(summary)
    else:
        try:
            with open(brief_path, "r", encoding="utf-8") as f:
                brief_content = f.read()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to read brief: {str(e)}")

    return {
        "iteration_id": iteration_id,
        "brief": brief_content,
        "format": "markdown",
    }


@router.get("/{iteration_id}/artifacts", response_model=ArtifactsResponse)
async def get_iteration_artifacts(iteration_id: str):
    """
    获取迭代产物清单

    返回产物路径列表及存在性检查
    """
    summary = _load_summary(iteration_id)

    if not summary:
        raise HTTPException(status_code=404, detail=f"Iteration '{iteration_id}' not found")

    artifacts = summary.get("artifacts", {})
    missing = []
    all_exist = True

    for name, path in artifacts.items():
        if path:
            full_path = Path(path)
            if not full_path.exists():
                missing.append(f"{name}: {path}")
                all_exist = False

    return ArtifactsResponse(
        iteration_id=iteration_id,
        artifacts=artifacts,
        all_exist=all_exist,
        missing=missing,
    )


@router.delete("/{iteration_id}")
async def delete_iteration(iteration_id: str):
    """
    删除迭代

    仅删除迭代目录（谨慎使用）
    """
    import shutil

    iter_dir = _get_iteration_dir(iteration_id)

    if not iter_dir.exists():
        raise HTTPException(status_code=404, detail=f"Iteration '{iteration_id}' not found")

    try:
        shutil.rmtree(iter_dir)
        return {"message": f"Iteration '{iteration_id}' deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete iteration: {str(e)}")
