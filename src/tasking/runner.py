"""
单任务执行器 -- 在子进程中运行，调用现有 pipeline
"""
from __future__ import annotations

import json
import logging
import os
import traceback
from datetime import datetime

import yaml


class _CancelledError(Exception):
    pass


def _check_cancel(cancel_flag: str, task_id: str):
    if os.path.exists(cancel_flag):
        raise _CancelledError(f"任务 {task_id} 在安全检查点检测到取消标记")


# 步骤进度范围配置
# 特征计算单独使用 0-100%，其他步骤映射到全局
STEP_PROGRESS = {
    "download": (0, 100),
    "etl": (0, 100),
    "raw_feature": (0, 100),  # 特征矩阵计算直接 0-100%
    "neutralize": (0, 100),
    "feature": (0, 100),
    "backtest": (0, 100),
    "factor_analysis": (0, 100),
}


def run_task(config_snapshot_path: str, output_dir: str, db_path: str, task_id: str):
    """
    子进程入口: 加载快照 cfg -> 执行 pipeline -> 写结果。
    此函数将被 ProcessPoolExecutor 调用。
    依赖 pyproject.toml editable install，不再需要 sys.path 操作。
    """
    from src.tasking.store import TaskStore
    from src.tasking.models import TaskStatus

    store = TaskStore(db_path)

    # 设置任务级日志
    log_dir = os.path.join(output_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, "runtime.log")
    logging.basicConfig(
        filename=log_path,
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        encoding="utf-8",
        force=True,
    )
    logger = logging.getLogger(f"task.{task_id}")

    # 创建进度回调 - 直接传递进度
    def make_progress_cb(step_name: str):
        """创建步骤内的进度回调，直接传递 0-100% 进度"""
        def cb(sub_pct: int, msg: str = ""):
            store.update_progress(task_id, sub_pct, msg)
            logger.info(f"[{step_name}] {sub_pct}% - {msg}")

        return cb

    try:
        store.update_status(
            task_id, TaskStatus.RUNNING,
            started_at=datetime.now().isoformat(),
            pid=os.getpid(),
        )
        logger.info(f"任务 {task_id} 开始执行, PID={os.getpid()}")

        with open(config_snapshot_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        steps = cfg.get("_task", {}).get("steps", ["raw_feature", "neutralize", "backtest"])
        logger.info(f"执行步骤: {steps}")

        # 确保输出子目录
        for sub in ("features", "models", "logs", "results"):
            os.makedirs(os.path.join(output_dir, sub), exist_ok=True)

        # 重定向输出路径到任务目录
        # 注意: raw_feature_output 保持原路径，共享增量缓存
        cfg["features"]["output"] = os.path.join(output_dir, "features", "alpha158.parquet")
        # raw_feature_output 不重定向，保持正式路径以复用增量缓存
        cfg["paths"]["models"] = os.path.join(output_dir, "models")
        cfg["paths"]["logs"] = os.path.join(output_dir, "logs")
        cfg["paths"]["data_features"] = os.path.join(output_dir, "features")
        ana = cfg.get("analysis", {})
        ana["ic_output"] = os.path.join(output_dir, "features", "ic_series.parquet")
        ana["icir_output"] = os.path.join(output_dir, "features", "icir.parquet")
        ana["ic_decay_output"] = os.path.join(output_dir, "features", "ic_decay.parquet")
        ana["shap_output"] = os.path.join(output_dir, "features", "shap_importance.parquet")
        cfg["analysis"] = ana

        cancel_flag = os.path.join(output_dir, ".cancel")

        from pipeline import (
            run_raw_feature_pipeline, run_neutralize_pipeline,
            run_feature_pipeline, run_backtest_pipeline, run_factor_analysis,
        )
        from src.data_hub import run_downloader, merge_and_clean

        metrics = {}
        asset_ids: dict = {}
        raw_df = None
        t_all_features = None
        t_gfm = None

        if "download" in steps:
            _check_cancel(cancel_flag, task_id)
            logger.info("阶段: download")
            store.update_progress(task_id, 5, "下载数据...")
            run_downloader(cfg)

        if "etl" in steps:
            _check_cancel(cancel_flag, task_id)
            logger.info("阶段: etl")
            store.update_progress(task_id, 15, "ETL 清洗...")
            merge_and_clean(cfg)

        # 兼容旧步骤名 "feature" = raw_feature + neutralize
        if "feature" in steps:
            _check_cancel(cancel_flag, task_id)
            logger.info("阶段: feature (raw + neutralize)")
            store.update_progress(task_id, 20, "特征计算...")
            _, asset_ids = run_feature_pipeline(
                cfg, progress_cb=make_progress_cb("feature")
            )
        else:
            if "raw_feature" in steps:
                _check_cancel(cancel_flag, task_id)
                logger.info("阶段: raw_feature")
                raw_df, t_all_features, t_gfm = run_raw_feature_pipeline(
                    cfg, progress_cb=make_progress_cb("raw_feature")
                )

            if "neutralize" in steps:
                _check_cancel(cancel_flag, task_id)
                logger.info("阶段: neutralize")
                _, asset_ids = run_neutralize_pipeline(
                    cfg, raw_df, t_all_features, t_gfm,
                    progress_cb=make_progress_cb("neutralize"),
                )

        if "backtest" in steps:
            _check_cancel(cancel_flag, task_id)
            logger.info("阶段: backtest")
            results_df, metrics = run_backtest_pipeline(
                cfg, output_dir=output_dir,
                feature_set_id=asset_ids.get("feature_set_id"),
                label_set_id=asset_ids.get("label_set_id"),
                progress_cb=make_progress_cb("backtest"),
            )

            results_dir = os.path.join(output_dir, "results")
            results_df.to_parquet(
                os.path.join(results_dir, "backtest_results.parquet"),
                index=False, engine="pyarrow",
            )
            scalar_metrics = {
                k: (v.item() if hasattr(v, "item") else v)
                for k, v in metrics.items()
                if isinstance(v, (int, float, str, bool, type(None)))
                or hasattr(v, "item")
            }
            with open(os.path.join(results_dir, "metrics.json"), "w", encoding="utf-8") as f:
                json.dump(scalar_metrics, f, indent=2, ensure_ascii=False)
            logger.info(f"回测完成, 指标: {scalar_metrics}")

        if "factor_analysis" in steps:
            _check_cancel(cancel_flag, task_id)
            logger.info("阶段: factor_analysis")
            run_factor_analysis(
                cfg,
                feature_set_id=asset_ids.get("feature_set_id"),
                label_set_id=asset_ids.get("label_set_id"),
            )

        store.update_status(
            task_id, TaskStatus.SUCCEEDED,
            finished_at=datetime.now().isoformat(),
        )
        store.update_progress(task_id, 100, "完成")
        logger.info(f"任务 {task_id} 成功完成")
        return {"status": "succeeded", "task_id": task_id}

    except _CancelledError:
        store.update_status(
            task_id, TaskStatus.CANCELLED,
            finished_at=datetime.now().isoformat(),
            error_message="用户取消",
        )
        logger.warning(f"任务 {task_id} 被取消")
        return {"status": "cancelled", "task_id": task_id}

    except Exception as exc:
        tb = traceback.format_exc()
        err_msg = f"{type(exc).__name__}: {exc}"
        store.update_status(
            task_id, TaskStatus.FAILED,
            finished_at=datetime.now().isoformat(),
            error_message=err_msg,
        )
        logger.error(f"任务 {task_id} 失败: {err_msg}\n{tb}")
        return {"status": "failed", "task_id": task_id, "error": err_msg}
