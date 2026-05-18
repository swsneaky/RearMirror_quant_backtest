"""
HPO 状态 API

端点:
  GET /api/hpo/status  -- 获取 HPO 运行状态
  GET /api/hpo/trials  -- 获取 Trial 列表
  GET /api/hpo/{study_name}/report  -- 获取 HPO 研究报告
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pathlib import Path
import json
import os
from typing import Optional
from pydantic import BaseModel
from datetime import datetime

router = APIRouter(prefix="/api/hpo", tags=["hpo"])

HPO_DIR = Path("data/results/hpo")


class HPOStatus(BaseModel):
    """HPO 状态 - 匹配前端 HPOStatus 接口"""
    study_name: Optional[str] = None
    model: Optional[str] = None  # 前端期望 model 而非 model_name
    objective_metric: Optional[str] = None
    status: str = "not_started"
    current_trial: int = 0  # 当前试验编号
    total_trials: int = 0   # 总试验数 (原 n_trials)
    best_value: Optional[float] = None
    elapsed_seconds: float = 0.0  # 已耗时(秒)


class HPOStatusResponse(BaseModel):
    """HPO 状态响应"""
    status: HPOStatus
    available_studies: list[str]


class TrialResult(BaseModel):
    """单个 Trial 结果"""
    number: int
    state: str
    value: Optional[float] = None
    params: dict = {}


class HPOTrialsResponse(BaseModel):
    """HPO Trials 响应"""
    study_name: Optional[str] = None
    trials: list[TrialResult]
    total: int


@router.get("/status", response_model=HPOStatusResponse)
async def get_hpo_status():
    """
    获取 HPO 运行状态

    扫描 .db 文件，返回最新状态
    """
    import sqlite3
    from datetime import datetime

    available_studies = []

    if not HPO_DIR.exists():
        return HPOStatusResponse(
            status=HPOStatus(status="not_started"),
            available_studies=[]
        )

    # 扫描所有 .db 文件
    db_files = list(HPO_DIR.glob("*.db"))
    for db_file in db_files:
        available_studies.append(db_file.stem)

    if not db_files:
        return HPOStatusResponse(
            status=HPOStatus(status="not_started"),
            available_studies=[]
        )

    # 获取最新的 study (按文件修改时间)
    latest_db = max(db_files, key=lambda f: f.stat().st_mtime)
    study_name = latest_db.stem

    # 从数据库获取实时信息
    current_trial = 0
    total_trials = 0
    elapsed_seconds = 0.0
    run_status = "completed"

    try:
        conn = sqlite3.connect(str(latest_db))
        cursor = conn.cursor()

        # 获取已完成和总试验数
        cursor.execute("SELECT COUNT(*) FROM trials WHERE state = 'COMPLETE'")
        current_trial = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM trials")
        total_trials = cursor.fetchone()[0]

        # 检查是否有 RUNNING 状态
        cursor.execute("SELECT COUNT(*) FROM trials WHERE state = 'RUNNING'")
        running_count = cursor.fetchone()[0]
        if running_count > 0:
            run_status = "running"

        # 计算总耗时
        cursor.execute("""
            SELECT MIN(datetime_start), MAX(datetime_complete)
            FROM trials
        """)
        row = cursor.fetchone()
        if row[0] and row[1]:
            start = datetime.fromisoformat(row[0])
            end = datetime.fromisoformat(row[1])
            elapsed_seconds = (end - start).total_seconds()

        conn.close()
    except Exception:
        pass

    # 尝试读取 summary.json
    summary_path = HPO_DIR / f"{study_name}_summary.json"

    status = HPOStatus(
        study_name=study_name,
        status=run_status,
        current_trial=current_trial,
        total_trials=total_trials,
        elapsed_seconds=elapsed_seconds
    )

    if summary_path.exists():
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            status.study_name = data.get("study_name")
            status.model = data.get("model_name")  # model_name -> model
            status.objective_metric = data.get("objective_metric")
            status.best_value = data.get("best_value")
            # total_trials 从数据库获取更准确，但 summary 可作为备用
            if total_trials == 0:
                status.total_trials = data.get("n_trials", 0)
        except Exception:
            pass

    return HPOStatusResponse(
        status=status,
        available_studies=available_studies
    )


@router.get("/trials", response_model=HPOTrialsResponse)
async def get_hpo_trials():
    """
    获取 Trial 列表

    读取最新的 trials.parquet 文件
    """
    import pandas as pd

    if not HPO_DIR.exists():
        return HPOTrialsResponse(trials=[], total=0)

    # 找到最新的 trials.parquet
    trials_files = list(HPO_DIR.glob("*_trials.parquet"))

    if not trials_files:
        return HPOTrialsResponse(trials=[], total=0)

    latest_trials = max(trials_files, key=lambda f: f.stat().st_mtime)
    study_name = latest_trials.stem.replace("_trials", "")

    try:
        df = pd.read_parquet(latest_trials)

        # 找出所有 params_ 开头的列
        params_cols = [col for col in df.columns if col.startswith("params_")]

        trials = []
        for _, row in df.iterrows():
            # 收集所有 params_* 列到 params dict
            params = {}
            for col in params_cols:
                param_name = col.replace("params_", "")
                value = row.get(col)
                if pd.notna(value):
                    params[param_name] = value

            trial = TrialResult(
                number=int(row.get("number", 0)),
                state=row.get("state", "UNKNOWN"),
                value=float(row.get("value")) if pd.notna(row.get("value")) else None,
                params=params
            )
            trials.append(trial)

        return HPOTrialsResponse(
            study_name=study_name,
            trials=trials,
            total=len(trials)
        )
    except Exception as e:
        return HPOTrialsResponse(trials=[], total=0)


@router.get("/{study_name}/report")
async def get_hpo_report(study_name: str):
    """
    获取 HPO 研究报告

    返回 HPO summary.json 内容和生成的 Markdown 报告
    """
    from src.reporting.brief_generator import generate_hpo_report

    summary_path = HPO_DIR / f"{study_name}_summary.json"

    if not summary_path.exists():
        raise HTTPException(status_code=404, detail=f"HPO study '{study_name}' not found")

    try:
        with open(summary_path, "r", encoding="utf-8") as f:
            study_data = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read HPO summary: {str(e)}")

    # 尝试加载 trial 数据
    trials_path = HPO_DIR / f"{study_name}_trials.parquet"
    trial_data = None

    if trials_path.exists():
        try:
            import pandas as pd
            df = pd.read_parquet(trials_path)
            trial_data = []
            for _, row in df.iterrows():
                trial_data.append({
                    "number": int(row.get("number", 0)),
                    "state": row.get("state", "UNKNOWN"),
                    "value": float(row.get("value")) if pd.notna(row.get("value")) else None,
                })
        except Exception:
            pass

    # 生成 Markdown 报告
    report_content = generate_hpo_report(study_data, trial_data)

    return {
        "study_name": study_name,
        "summary": study_data,
        "report": report_content,
        "format": "markdown",
    }
