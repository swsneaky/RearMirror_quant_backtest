"""
主流水线编排器 -- 一键贯通 ETL -> Feature -> Neutralize -> Label -> Backtest

迭代循环架构:
  1. 特征工程 (raw)   -- 全量计算所有注册因子, 存储原始矩阵 (支持增量更新)
  2. 因子粗筛          -- active_factors 选组 + excluded_features 剔除个体
  3. 截面中性化         -- 仅对筛选后的因子做 MAD + 行业中性化 + Z-Score
  4. 模型训练 + 回测    -- Walk-Forward 滚动验证
  5. 因子精筛           -- 通过 IC/ICIR/SHAP 进一步筛选, 进入下一轮迭代

分层:
  - FeatureStore / LabelStore / DatasetBuilder 实现资产分层
  - 回测结果通过 ExperimentStore 标准化落盘
  - 为 Dashboard 兼容，继续生成 legacy merged parquet (过渡产物)
"""
from __future__ import annotations

import gc
import logging
import os
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

from src.config_loader import load_config
from src.data_hub import run_downloader, merge_and_clean
from src.feature_engine import build_alpha158
from src.cross_section import cross_sectional_process
from src.label_gen import compute_label_values, generate_labels
from src.price_mode import apply_price_mode, get_price_mode
from src.ml_core.backtest import run_walk_forward, evaluate
from src.factors.ic_analysis import run_ic_analysis
from src.data_layer import FeatureStore, LabelStore, DatasetBuilder
from src.experiment_store import (
    ExperimentStore, build_holdings_from_predictions, build_nav_from_metrics,
)
from src.runtime_modes import apply_runtime_mode_to_config


# ====================================================
# HPO 模块导入
# ====================================================
from src.hpo import run_hpo_pipeline as _run_hpo_pipeline


def run_hpo_pipeline(
    cfg: dict | None = None,
    n_trials: int = 50,
    objective_metric: str = "sharpe_ratio",
    model_name: str | None = None,
    study_name: str | None = None,
    resume: bool = False,
    output_dir: str | None = None,
    n_jobs: int = 1,
    timeout: float | None = None,
    verbose: bool = True,
) -> dict:
    """
    超参数优化入口

    Args:
        cfg: 配置字典
        n_trials: 优化试验次数
        objective_metric: 优化目标 (sharpe_ratio, ic_mean, icir, annual_return)
        model_name: 模型名称 (None 则使用配置中的 active 模型)
        study_name: 研究名称
        resume: 是否恢复已有研究
        output_dir: 输出目录 (None 则从配置读取或使用默认值)
        n_jobs: 并行数 (建议为 1，避免模型内部并行冲突)
        timeout: 超时时间 (秒)
        verbose: 是否打印详细信息

    Returns:
        优化结果字典
    """
    return _run_hpo_pipeline(
        cfg=cfg,
        n_trials=n_trials,
        objective_metric=objective_metric,
        model_name=model_name,
        study_name=study_name,
        resume=resume,
        output_dir=output_dir,
        n_jobs=n_jobs,
        timeout=timeout,
        verbose=verbose,
    )


# ====================================================
# 阶段入口：原始特征工程 (步骤 1)
# ====================================================
def run_raw_feature_pipeline(
    cfg: dict | None = None,
    progress_cb=None,
) -> tuple[pd.DataFrame, list[str], dict[str, list[str]]]:
    """
    ETL 产物 -> Alpha158 因子裂变 -> 原始特征矩阵落盘 (真增量更新)。

    此步骤**不做中性化**, 只计算原始因子值。
    产出的原始矩阵可复用于不同因子组合的中性化, 避免重复计算。

    DB-first incremental protocol:
      - Read existing raw feature state from SQLite feature_wide.
      - Compute factors from a daily_bar warmup slice and upsert only new dates.
      - Parquet is an optional snapshot/export, not the incremental source of truth.

    Returns: (raw_df, all_features, group_feature_map)
    """
    if cfg is None:
        cfg = load_config()

    def _progress(pct: int, msg: str):
        if progress_cb:
            progress_cb(pct, msg)

    feat_cfg = cfg["features"]
    raw_output = feat_cfg.get("raw_feature_output", "data/features/zz500_alpha158_raw.parquet")
    active_factors = feat_cfg.get("active_factors")

    feature_store = FeatureStore.from_config(cfg)
    raw_extra_cols = ["isST", "tradestatus", "raw_pctChg", "raw_amount"]

    def _select_raw_feature_cols(frame: pd.DataFrame, features: list[str]) -> pd.DataFrame:
        meta_cols = [
            c
            for c in ["date", "code", "industry", *raw_extra_cols]
            if c in frame.columns
        ]
        keep = meta_cols + [c for c in features if c in frame.columns and c not in meta_cols]
        out = frame[keep].copy()
        out["date"] = pd.to_datetime(out["date"])
        out["code"] = out["code"].astype(str)
        return out.sort_values(["code", "date"]).reset_index(drop=True)

    def _ensure_industry(frame: pd.DataFrame) -> pd.DataFrame:
        needs_industry = "industry" not in frame.columns or frame["industry"].isna().any()
        if not needs_industry:
            return frame

        out = frame.copy()
        try:
            from src.data_layer.canonical import CanonicalStore

            ind_df = CanonicalStore.from_config(cfg).load_industry()
            if "industry" in out.columns:
                out = out.drop(columns=["industry"])
            out = out.merge(ind_df, on="code", how="left")
        except Exception as exc:
            logger.warning("raw feature incremental industry map load failed: %s", exc)
            if "industry" not in out.columns:
                out["industry"] = "Unknown"
        out["industry"] = out["industry"].fillna("Unknown")
        return out

    def _record_raw_feature_fingerprint(
        frame: pd.DataFrame,
        features: list[str],
        *,
        source: str,
    ) -> None:
        n_stocks = int(frame["code"].nunique()) if "code" in frame.columns else 0
        try:
            from src.storage_manager import save_fingerprint

            save_fingerprint(
                raw_output,
                cfg,
                sections=["etl", "features", "price"],
                row_count=len(frame),
                extra={
                    "n_features": len(features),
                    "n_stocks": n_stocks,
                    "type": "raw",
                    "source": source,
                },
            )
        except Exception as exc:
            logger.warning("raw feature fingerprint save failed: %s", exc)

        try:
            from src.data_layer.layer_manager import DataLayerManager

            DataLayerManager(cfg).save_raw_feature_fingerprint(
                row_count=len(frame),
                n_stocks=n_stocks,
                n_features=len(features),
            )
        except Exception as exc:
            logger.warning("raw feature layer fingerprint save failed: %s", exc)

    def _run_initial_full_build() -> tuple[pd.DataFrame, list[str], dict[str, list[str]]]:
        _progress(5, "Full raw feature build from canonical store...")

        def full_progress_cb(pct: int, msg: str):
            if progress_cb:
                progress_cb(5 + int(pct * 0.9), msg)

        df, all_features, group_feature_map = build_alpha158(
            cfg,
            progress_cb=full_progress_cb,
            factor_groups=active_factors,
        )
        raw_df = _select_raw_feature_cols(df, all_features)
        stats = feature_store.upsert_raw_features(
            raw_df,
            all_features,
            extra_cols=raw_extra_cols,
            snapshot_path=raw_output,
            export_snapshot=True,
        )
        _record_raw_feature_fingerprint(raw_df, all_features, source="db_first_full_build")
        print(
            "[FULL] raw feature DB-first initial build: "
            f"rows={len(raw_df):,} features={len(all_features)} "
            f"snapshot_written={stats['snapshot_written']}",
            flush=True,
        )
        _progress(100, f"Done: {len(all_features)} raw features")
        return raw_df, all_features, group_feature_map

    def _run_db_first_increment(
        state: dict[str, Any],
    ) -> tuple[pd.DataFrame, list[str], dict[str, list[str]]]:
        from src.data_layer.db import (
            get_connection,
            get_pending_rebuild_codes,
            mark_rebuild_codes_done,
        )

        old_max = pd.to_datetime(state["max_date"]).normalize()
        old_max_str = old_max.strftime("%Y-%m-%d")
        all_features = list(state["features"])
        group_feature_map = globals()["_infer_group_feature_map"](all_features, cfg)

        _progress(5, "Checking SQLite daily_bar for new trading dates...")
        con = get_connection(cfg)
        latest_row = con.execute("SELECT MAX(DATE(date)) FROM daily_bar").fetchone()
        if latest_row is None or latest_row[0] is None:
            raise RuntimeError("DB-first raw feature incremental failed: daily_bar is empty")

        daily_max = pd.to_datetime(latest_row[0]).normalize()
        rebuild_codes = get_pending_rebuild_codes(cfg)

        new_dates_df = con.execute(
            """
            SELECT DISTINCT DATE(date) AS date
            FROM daily_bar
            WHERE DATE(date) > DATE(?)
            ORDER BY DATE(date)
            """,
            [old_max_str],
        ).df()
        if new_dates_df.empty:
            new_dates = pd.Series(dtype="datetime64[ns]")
        else:
            new_dates = pd.to_datetime(new_dates_df["date"]).dt.normalize()
        n_new_dates = int(len(new_dates))

        if n_new_dates == 0 and not rebuild_codes:
            raw_df = feature_store.load()
            print(
                "[INCR] raw feature DB-first no-op: "
                f"old_feature_max={old_max.date()} daily_bar_max={daily_max.date()} "
                "new_trading_dates=0 rebuild_codes=0 upserted_rows=0 snapshot_written=False",
                flush=True,
            )
            _progress(100, "No new daily_bar dates and no rebuild codes; reused SQLite feature store")
            return raw_df, all_features, group_feature_map

        upsert_parts: list[pd.DataFrame] = []
        computed_features = list(all_features)
        computed_group_map = dict(group_feature_map)
        warmup_start: pd.Timestamp | None = None

        if n_new_dates > 0:
            max_window = max(feat_cfg["windows"])
            warmup_days = max_window + 10
            date_limit = int(warmup_days + n_new_dates)
            dates_df = con.execute(
                """
                SELECT DISTINCT DATE(date) AS date
                FROM daily_bar
                WHERE DATE(date) <= DATE(?)
                ORDER BY DATE(date) DESC
                LIMIT ?
                """,
                [daily_max.strftime("%Y-%m-%d"), date_limit],
            ).df()
            if dates_df.empty:
                raise RuntimeError("DB-first raw feature incremental failed: no warmup dates found")

            dates_df["date"] = pd.to_datetime(dates_df["date"]).dt.normalize()
            warmup_start = dates_df["date"].min()
            warmup_start_str = warmup_start.strftime("%Y-%m-%d")
            daily_max_str = daily_max.strftime("%Y-%m-%d")

            slice_df = con.execute(
                """
                SELECT *
                FROM daily_bar
                WHERE DATE(date) >= DATE(?) AND DATE(date) <= DATE(?)
                ORDER BY code, date
                """,
                [warmup_start_str, daily_max_str],
            ).df()
            if slice_df.empty:
                raise RuntimeError("DB-first raw feature incremental failed: warmup slice is empty")
            slice_df["date"] = pd.to_datetime(slice_df["date"])
            slice_df = _ensure_industry(slice_df)

            print(
                "[INCR] raw feature DB-first start: "
                f"old_feature_max={old_max.date()} daily_bar_max={daily_max.date()} "
                f"new_trading_dates={n_new_dates} warmup_start={warmup_start.date()} "
                f"slice_rows={len(slice_df):,} rebuild_codes={len(rebuild_codes)}",
                flush=True,
            )
            _progress(10, f"Incremental raw feature build for {n_new_dates} new dates...")

            try:
                def incr_progress_cb(pct: int, msg: str):
                    if progress_cb:
                        progress_cb(10 + int(pct * 0.6), msg)

                computed_df, inc_features, inc_group_map = build_alpha158(
                    cfg,
                    progress_cb=incr_progress_cb,
                    factor_groups=active_factors,
                    input_df=slice_df,
                )
            except Exception as exc:
                raise RuntimeError(
                    "DB-first raw feature incremental failed; full recompute fallback was not attempted"
                ) from exc

            computed_df["date"] = pd.to_datetime(computed_df["date"])
            computed_dates = computed_df["date"].dt.normalize()
            new_rows = computed_df[computed_dates > old_max].copy()
            if new_rows.empty:
                raise RuntimeError(
                    "DB-first raw feature incremental produced no rows for new trading dates; "
                    "full recompute fallback was not attempted"
                )

            raw_new_rows = _select_raw_feature_cols(new_rows, inc_features)
            if rebuild_codes:
                raw_new_rows = raw_new_rows[~raw_new_rows["code"].isin(rebuild_codes)].copy()

            upsert_parts.append(raw_new_rows)
            computed_features = inc_features
            computed_group_map = inc_group_map

        if rebuild_codes:
            placeholders = ", ".join(["?"] * len(rebuild_codes))
            rebuild_slice = con.execute(
                f"""
                SELECT *
                FROM daily_bar
                WHERE code IN ({placeholders})
                ORDER BY code, date
                """,
                rebuild_codes,
            ).df()

            if rebuild_slice.empty:
                print("[REBUILD] queued rebuild codes had no rows in daily_bar; skipping rebuild slice", flush=True)
            else:
                rebuild_slice["date"] = pd.to_datetime(rebuild_slice["date"])
                rebuild_slice = _ensure_industry(rebuild_slice)
                _progress(75, f"Historical rebuild for {len(rebuild_codes)} codes...")

                def rebuild_progress_cb(pct: int, msg: str):
                    if progress_cb:
                        progress_cb(75 + int(pct * 0.2), f"[rebuild] {msg}")

                rebuild_df, rebuild_features, rebuild_group_map = build_alpha158(
                    cfg,
                    progress_cb=rebuild_progress_cb,
                    factor_groups=active_factors,
                    input_df=rebuild_slice,
                )
                raw_rebuild_rows = _select_raw_feature_cols(rebuild_df, rebuild_features)
                upsert_parts.append(raw_rebuild_rows)

                if not n_new_dates:
                    computed_features = rebuild_features
                    computed_group_map = rebuild_group_map
                else:
                    computed_features = sorted(set(computed_features) | set(rebuild_features))
                    computed_group_map.update(rebuild_group_map)

        if not upsert_parts:
            raw_df = feature_store.load()
            _progress(100, "No rows selected for upsert; reused SQLite feature store")
            return raw_df, computed_features, computed_group_map

        upsert_df = pd.concat(upsert_parts, ignore_index=True)
        upsert_df = upsert_df.drop_duplicates(subset=["date", "code"], keep="last")

        stats = feature_store.upsert_raw_features(
            upsert_df,
            computed_features,
            extra_cols=raw_extra_cols,
            snapshot_path=raw_output,
            export_snapshot=True,
        )
        if rebuild_codes:
            mark_rebuild_codes_done(cfg, rebuild_codes)

        raw_df = feature_store.load()
        _record_raw_feature_fingerprint(raw_df, computed_features, source="db_first_incremental_event_driven")

        warmup_label = warmup_start.date() if warmup_start is not None else "n/a"
        print(
            "[INCR] raw feature DB-first stats: "
            f"old_feature_max={old_max.date()} daily_bar_max={daily_max.date()} "
            f"new_trading_dates={n_new_dates} rebuild_codes={len(rebuild_codes)} "
            f"warmup_start={warmup_label} upserted_rows={stats['upserted_rows']:,} "
            f"feature_rows {stats['row_count_before']:,}->{stats['row_count_after']:,} "
            f"snapshot_written={stats['snapshot_written']}",
            flush=True,
        )
        if stats.get("snapshot_error"):
            print(f"[SNAPSHOT] raw feature snapshot skipped/error: {stats['snapshot_error']}", flush=True)

        _progress(100, f"Done: upserted {stats['upserted_rows']:,} raw feature rows")
        return raw_df, computed_features, computed_group_map

    _progress(0, "Checking SQLite feature state for DB-first raw feature pipeline...")
    feature_state = feature_store.get_feature_state()
    if feature_state is None:
        return _run_initial_full_build()
    return _run_db_first_increment(feature_state)

    # ── 增量更新检测 ──
    _progress(0, "检测增量更新...")
    incremental_ok = False
    existing = None

    # 先检查原始矩阵是否存在
    if os.path.exists(raw_output):
        try:
            # 只读取日期列获取最新日期，避免加载整个文件
            import pyarrow.parquet as pq
            date_table = pq.read_table(raw_output, columns=['date'])
            existing_dates = date_table['date'].to_pandas()
            existing_dates = pd.to_datetime(existing_dates)
            old_max = existing_dates.max()

            # 获取因子列名
            parquet_file = pq.ParquetFile(raw_output)
            all_columns = parquet_file.schema_arrow.names
            existing_features = [c for c in all_columns if c.startswith("feat_")]

            if existing_features:
                print(f"[CACHE] 发现原始矩阵缓存: {raw_output}")
                print(f"   {len(existing_dates):,} 行, {len(existing_features)} 因子, "
                      f"日期范围 {existing_dates.min().date()} ~ {old_max.date()}")

                # 检查配置是否变更（如果有指纹文件）
                try:
                    from src.storage_manager import check_cache_fresh
                    is_fresh, reason = check_cache_fresh(
                        raw_output,
                        cfg,
                        sections=["etl", "features", "price"],
                    )
                    if not is_fresh:
                        print(f"[CACHE] 配置已变更: {reason}，将重新计算增量部分")
                except Exception:
                    # 指纹文件不存在，仍可增量
                    print("[CACHE] 无指纹文件，基于日期范围增量更新")

                incremental_ok = True
        except Exception as exc:
            logger.warning("读取缓存失败: %s", exc)

    if incremental_ok:
        # ── 真增量: 检查是否有新交易日 ──
        _progress(5, "检查新交易日...")
        try:
            # 直接查询数据库获取最新日期，避免加载全量数据
            import sqlite3
            db_path = cfg.get("paths", {}).get("database", "data/quant.db")
            conn = sqlite3.connect(db_path)

            # 获取新交易日列表 (使用 DATE() 确保日期格式一致)
            old_max_str = old_max.strftime('%Y-%m-%d')
            new_dates_df = pd.read_sql_query(
                f"SELECT DISTINCT DATE(date) as date FROM daily_bar WHERE DATE(date) > DATE('{old_max_str}') ORDER BY date",
                conn
            )

            # 获取最新日期
            result = conn.execute("SELECT MAX(DATE(date)) FROM daily_bar").fetchone()
            conn.close()

            n_new_dates = len(new_dates_df)

            if n_new_dates == 0:
                # 无新数据, 直接复用缓存
                print("[CACHE] 无新增交易日, 复用缓存")
                _progress(100, "无新增数据，复用缓存")
                from pipeline import _infer_group_feature_map
                group_feature_map = _infer_group_feature_map(existing_features, cfg)
                # 返回 None 表示复用现有文件
                return None, existing_features, group_feature_map

            # 有新数据: 计算预热起点
            latest_available = pd.to_datetime(result[0], format='mixed').normalize()
            max_window = max(feat_cfg["windows"])
            safety_margin = 10  # 额外安全边际 (交易日)
            warmup_days = max_window + safety_margin

            # 获取预热期间的交易日
            conn = sqlite3.connect(db_path)
            dates_df = pd.read_sql_query(
                "SELECT DISTINCT date FROM daily_bar ORDER BY date DESC LIMIT ?",
                conn, params=(warmup_days + n_new_dates,)
            )
            conn.close()

            # 处理日期格式 (可能是 YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS)
            dates_df['date'] = pd.to_datetime(dates_df['date'], format='mixed').dt.normalize()
            dates_df = dates_df.sort_values('date')
            warmup_start = dates_df['date'].iloc[0]

            print(f"[INCR] 检测到 {n_new_dates} 个新交易日 "
                  f"(最新 {latest_available.date()}, 缓冲起点 {warmup_start.date()})")

            # 加载切片数据
            conn = sqlite3.connect(db_path)
            slice_df = pd.read_sql_query(
                f"SELECT * FROM daily_bar WHERE date >= '{warmup_start.date()}' ORDER BY code, date",
                conn
            )
            conn.close()

            # 合并行业映射
            try:
                from src.data_layer.canonical import CanonicalStore
                store = CanonicalStore.from_config(cfg)
                ind_df = store.load_industry()
                slice_df = slice_df.merge(ind_df, on="code", how="left")
                slice_df["industry"] = slice_df["industry"].fillna("Unknown")
            except Exception as exc:
                logger.warning("增量模式行业映射加载失败: %s", exc)
                slice_df["industry"] = "Unknown"

            print(f"   切片: {len(slice_df):,} 行, 从 {warmup_start.date()} 开始")
            _progress(10, f"增量计算 {n_new_dates} 个新交易日...")

            # 增量计算因子
            def incr_progress_cb(pct: int, msg: str):
                if progress_cb:
                    mapped_pct = 10 + int(pct * 0.85)
                    progress_cb(mapped_pct, msg)

            df, all_features, group_feature_map = build_alpha158(
                cfg, progress_cb=incr_progress_cb,
                factor_groups=active_factors, input_df=slice_df,
            )

            # 仅保留新增行, 追加到旧缓存
            df["date"] = pd.to_datetime(df["date"], format='mixed')
            print(f"[DEBUG] df rows: {len(df):,}, date range: {df['date'].min().date()} ~ {df['date'].max().date()}")
            print(f"[DEBUG] old_max: {old_max.date()}")
            new_rows = df[df["date"] > old_max]
            print(f"[DEBUG] new_rows: {len(new_rows):,}")

            if not new_rows.empty:
                # 加载现有矩阵（仅需要追加时）
                print(f"[DEBUG] Loading existing matrix from {raw_output}")
                existing = pd.read_parquet(raw_output)
                existing["date"] = pd.to_datetime(existing["date"], format='mixed')
                print(f"[DEBUG] existing rows: {len(existing):,}")

                meta_cols = [c for c in ["date", "code", "industry", "isST", "tradestatus",
                                         "raw_pctChg", "raw_amount"] if c in df.columns]
                keep = meta_cols + all_features
                existing_keep = [c for c in keep if c in existing.columns]
                new_keep = [c for c in keep if c in new_rows.columns]
                print(f"[DEBUG] existing_keep: {len(existing_keep)} cols, new_keep: {len(new_keep)} cols")
                raw_df = pd.concat([
                    existing[existing_keep],
                    new_rows[new_keep],
                ], ignore_index=True)
                raw_df = raw_df.sort_values(["code", "date"]).reset_index(drop=True)
                print(f"[INCR] 追加 {len(new_rows):,} 行新数据 "
                      f"(旧 {len(existing):,} + 新 {len(new_rows):,} = {len(raw_df):,})")
                del existing  # 释放内存
            else:
                print("[INCR] 计算完成但无新增行 (可能窗口不足)")
                raw_df = df.copy()
            _progress(96, "合并增量数据...")
        except Exception as exc:
            logger.warning("Legacy parquet-first incremental path failed; blocking without full rebuild: %s", exc)
            raise RuntimeError(
                "Legacy raw feature incremental path failed; full recompute fallback is disabled"
            ) from exc
            # Legacy unreachable code below is retained only until the old parquet-first
            # branch is deleted; the raise above prevents any implicit full rebuild.
            _progress(10, "Incremental failed; full rebuild fallback is disabled")

            def full_progress_cb(pct: int, msg: str):
                if progress_cb:
                    mapped_pct = 10 + int(pct * 0.85)
                    progress_cb(mapped_pct, msg)

            df, all_features, group_feature_map = build_alpha158(
                cfg, progress_cb=full_progress_cb, factor_groups=active_factors,
            )
            meta_cols = [c for c in ["date", "code", "industry", "isST", "tradestatus",
                                     "raw_pctChg", "raw_amount"] if c in df.columns]
            raw_keep = meta_cols + all_features
            raw_df = df[[c for c in raw_keep if c in df.columns]].copy()
            raw_df = raw_df.sort_values(["code", "date"]).reset_index(drop=True)
    else:
        # ── 全量计算 (缓存不存在或已失效) ──
        _progress(5, "全量计算因子矩阵...")

        def full_progress_cb(pct: int, msg: str):
            if progress_cb:
                # 映射 0-100 到 5-95
                mapped_pct = 5 + int(pct * 0.9)
                progress_cb(mapped_pct, msg)

        df, all_features, group_feature_map = build_alpha158(
            cfg, progress_cb=full_progress_cb, factor_groups=active_factors,
        )
        meta_cols = [c for c in ["date", "code", "industry", "isST", "tradestatus",
                                 "raw_pctChg", "raw_amount"] if c in df.columns]
        raw_keep = meta_cols + all_features
        raw_df = df[[c for c in raw_keep if c in df.columns]].copy()
        raw_df = raw_df.sort_values(["code", "date"]).reset_index(drop=True)

    # ── 原始矩阵落盘 ──
    _progress(97, "保存特征矩阵...")
    os.makedirs(os.path.dirname(raw_output) or ".", exist_ok=True)
    raw_df.to_parquet(raw_output, index=False, engine="pyarrow")
    n_stocks = raw_df["code"].nunique() if "code" in raw_df.columns else 0
    print(f"\n[SAVE] 原始特征矩阵落盘: {raw_output}")
    print(f"   {raw_df.shape[0]:,} 行 x {len(all_features)} 因子 x {n_stocks} 只股票")

    # 缓存指纹 (原始矩阵 - 旧版，保留兼容)
    try:
        from src.storage_manager import save_fingerprint
        save_fingerprint(
            raw_output, cfg, sections=["etl", "features", "price"],
            row_count=len(raw_df),
            extra={"n_features": len(all_features), "n_stocks": n_stocks, "type": "raw"},
        )
    except Exception as exc:
        logger.warning("原始矩阵指纹保存失败: %s", exc)

    # v3: 数据层依赖指纹 (Layer 2: raw_feature)
    try:
        from src.data_layer.layer_manager import DataLayerManager
        mgr = DataLayerManager(cfg)
        mgr.save_raw_feature_fingerprint(
            row_count=len(raw_df),
            n_stocks=n_stocks,
            n_features=len(all_features),
        )
        logger.info("[LayerManager] Layer 2 (raw_feature) 指纹已保存")
    except Exception as exc:
        logger.warning("数据层指纹保存失败 (不影响主流程): %s", exc)

    _progress(100, f"完成: {len(all_features)} 个因子")
    return raw_df, all_features, group_feature_map


# ====================================================
# 阶段入口：因子筛选 + 中性化 + 标签 (步骤 2-3)
# ====================================================
def run_neutralize_pipeline(
    cfg: dict | None = None,
    raw_df: pd.DataFrame | None = None,
    all_features: list[str] | None = None,
    group_feature_map: dict[str, list[str]] | None = None,
    progress_cb=None,
    runtime_mode: str | None = None,
) -> tuple[pd.DataFrame, dict]:
    """
    原始特征矩阵 -> 因子粗筛 -> 截面中性化 -> 标签 -> 版本化落盘。

    如果不传 raw_df, 自动从 raw_feature_output 加载。

    因子组合 (selected_features + cross_section 参数) -> SHA hash -> 版本 key
    同一因子组合永远对应同一个中性化矩阵版本。

    Returns: (neutralized_df, asset_ids_dict)
    """
    if cfg is None:
        cfg = load_config()

    def _progress(pct: int, msg: str):
        if progress_cb:
            progress_cb(pct, msg)

    feat_cfg = cfg["features"]

    # ── 加载原始矩阵 (如未传入) ──
    _progress(0, "加载原始特征矩阵...")
    if raw_df is None:
        raw_output = feat_cfg.get("raw_feature_output", "data/features/zz500_alpha158_raw.parquet")
        if not os.path.exists(raw_output):
            raise FileNotFoundError(
                f"原始特征矩阵不存在: {raw_output}\n"
                "请先运行 run_raw_feature_pipeline() 生成原始矩阵"
            )
        print(f"[LOAD] 加载原始特征矩阵: {raw_output}")
        raw_df = pd.read_parquet(raw_output)
        raw_df["date"] = pd.to_datetime(raw_df["date"])
        if all_features is None:
            all_features = [c for c in raw_df.columns if c.startswith("feat_")]

    if all_features is None:
        all_features = [c for c in raw_df.columns if c.startswith("feat_")]

    # ── 还原 group_feature_map (如未传入) ──
    if group_feature_map is None:
        group_feature_map = _infer_group_feature_map(all_features, cfg)

    # ── 因子组合筛选: active_factors 选组 + excluded_features 剔除个体 ──
    _progress(5, "筛选因子组合...")
    active_groups = feat_cfg.get("active_factors", list(group_feature_map.keys()))
    excluded = set(feat_cfg.get("excluded_features", []))

    selected_features: list[str] = []
    for grp in active_groups:
        if grp not in group_feature_map:
            logger.warning("因子组 '%s' 未在原始矩阵中找到, 跳过", grp)
            continue
        for f in group_feature_map[grp]:
            if f not in excluded and f in raw_df.columns:
                selected_features.append(f)

    if not selected_features:
        raise ValueError(
            f"因子组合筛选后为空！active_factors={active_groups}, "
            f"excluded_features={excluded}, 可用组={list(group_feature_map.keys())}"
        )

    n_total = len(all_features)
    n_selected = len(selected_features)
    n_excluded = n_total - n_selected
    print(f"\n[FILTER] 因子组合筛选: 全量 {n_total} -> 选用 {n_selected} (排除 {n_excluded})")
    print(f"   选用因子组: {[g for g in active_groups if g in group_feature_map]}")
    if excluded:
        print(f"   额外排除: {sorted(excluded)}")

    # ── 截面中性化 (仅对选用因子) ──
    _progress(10, f"截面中性化 ({n_selected} 个因子)...")

    def neutralize_progress_cb(pct: int, msg: str):
        if progress_cb:
            # 映射 0-100 到 10-80
            mapped_pct = 10 + int(pct * 0.7)
            progress_cb(mapped_pct, msg)

    df = raw_df.copy()
    df = cross_sectional_process(
        df,
        selected_features,
        cfg,
        progress_cb=neutralize_progress_cb,
        runtime_mode=runtime_mode,
    )
    segment_plan = df.attrs.get("cross_section_segment_plan", {})
    if segment_plan:
        print(
            "[SEG] 中性化分段计划: "
            f"runtime_mode={segment_plan.get('runtime_mode', runtime_mode or 'formal')} "
            f"chunk_days={segment_plan.get('chunk_days')} "
            f"segment_count={segment_plan.get('segment_count')}",
            flush=True,
        )

    # ── 标签生成 ──
    _progress(85, "生成标签...")
    df = generate_labels(df, cfg)
    if segment_plan:
        df.attrs["cross_section_segment_plan"] = segment_plan
    print(f"[TAG] 标签生成完成，当前数据集: {df.shape[0]:,} 行 x {df.shape[1]} 列", flush=True)

    # --------------------------------------------------
    # 分层落盘：FeatureStore + LabelStore (新架构)
    # --------------------------------------------------
    _progress(90, "保存特征资产...")
    feature_config = {
        "selected_features": sorted(selected_features),
        "windows": feat_cfg["windows"],
        "cross_section": cfg.get("cross_section", {}),
        "price_mode": get_price_mode(cfg),
    }
    label_config = {
        **cfg.get("label", {}),
        "price_mode": get_price_mode(cfg),
    }

    # 收集当前 factor_ids
    factor_ids = []
    try:
        from src.registry import registry
        from src.data_layer.asset_id import make_factor_id
        for name in active_groups:
            code_hash = registry.get_factor_code_hash(name)
            if code_hash:
                factor_ids.append(make_factor_id(name, code_hash))
    except Exception:
        pass

    feature_store = FeatureStore.from_config(cfg)
    print("[PKG] 正在写入 FeatureStore / 版本化特征资产...", flush=True)
    _, feature_set_id = feature_store.save(
        df, selected_features,
        feature_config=feature_config, factor_ids=factor_ids,
    )

    label_store = LabelStore.from_config(cfg)
    print("[TAG] 正在写入 LabelStore / 版本化标签资产...", flush=True)
    _, label_set_id = label_store.save(df, cfg["label"]["name"], label_config=label_config)

    # --------------------------------------------------
    # 兼容性合并产物 (过渡：让 Dashboard 继续可用)
    # --------------------------------------------------
    filter_cols = [c for c in ["isST", "tradestatus"] if c in df.columns]
    backtest_cols = [c for c in ["raw_pctChg", "raw_amount"] if c in df.columns]
    keep_cols = (
        ["date", "code", "industry"]
        + filter_cols + backtest_cols
        + selected_features + [cfg["label"]["name"]]
    )
    df = df[[c for c in keep_cols if c in df.columns]]

    df = df.sort_values(["code", "date"]).reset_index(drop=True)
    out = cfg["features"]["output"]
    os.makedirs(os.path.dirname(out), exist_ok=True)
    print("[DONE] 正在写出 compat 合并产物 Parquet...", flush=True)
    df.to_parquet(out, index=False, engine="pyarrow")

    print(f"\n[DONE] 中性化特征矩阵落盘: {out}  ({df.shape[0]} 行 x {df.shape[1]} 列)", flush=True)
    print(f"   因子组合: {n_selected} 个因子 (版本: {feature_set_id})", flush=True)
    print(f"   [新架构] FeatureStore: {feature_store.store_path}", flush=True)
    print(f"   [新架构] LabelStore:   {label_store.store_path}", flush=True)

    # 缓存指纹 (中性化矩阵)
    try:
        from src.storage_manager import save_fingerprint
        save_fingerprint(
            out, cfg, sections=["etl", "features", "cross_section", "label", "price"],
            row_count=len(df),
            extra={"n_features": len(selected_features), "n_stocks": int(df["code"].nunique()),
                    "type": "neutralized"},
        )
    except Exception as exc:
        logger.warning("特征指纹保存失败: %s", exc)

    _progress(100, f"完成: {len(selected_features)} 个因子")
    gc.collect()
    return df, {"feature_set_id": feature_set_id, "label_set_id": label_set_id}


def _infer_group_feature_map(all_features: list[str], cfg: dict) -> dict[str, list[str]]:
    """
    从因子列名 + 配置反推 group_feature_map。
    用于从缓存加载原始矩阵时还原因子组归属。
    """
    feat_cfg = cfg.get("features", {})
    windows = feat_cfg.get("windows", [5, 10, 20, 30, 60])
    gfm: dict[str, list[str]] = {}

    # kline: feat_{bn} (no window)
    kline_bns = feat_cfg.get("kline_features", [])
    kline_feats = [f"feat_{bn}" for bn in kline_bns if f"feat_{bn}" in all_features]
    if kline_feats:
        gfm["kline"] = kline_feats

    # rolling: feat_{bn}{w}
    rolling_bns = feat_cfg.get("rolling_features", [])
    rolling_feats = [f"feat_{bn}{w}" for bn in rolling_bns for w in windows
                     if f"feat_{bn}{w}" in all_features]
    if rolling_feats:
        gfm["rolling"] = rolling_feats

    # rolling_ext: feat_{bn}{w}
    rext_bns = feat_cfg.get("rolling_ext_features", [])
    rext_feats = [f"feat_{bn}{w}" for bn in rext_bns for w in windows
                  if f"feat_{bn}{w}" in all_features]
    if rext_feats:
        gfm["rolling_ext"] = rext_feats

    # technical: per_window feat_{bn}{w} + fixed feat_{bn}
    tech_cfg = feat_cfg.get("technical_features", {})
    tech_pw = tech_cfg.get("per_window", [])
    tech_fx = tech_cfg.get("fixed", [])
    tech_feats = ([f"feat_{bn}{w}" for bn in tech_pw for w in windows
                   if f"feat_{bn}{w}" in all_features]
                  + [f"feat_{bn}" for bn in tech_fx if f"feat_{bn}" in all_features])
    if tech_feats:
        gfm["technical"] = tech_feats

    # turnover
    turn_cfg = feat_cfg.get("turnover_features", {})
    turn_pw = turn_cfg.get("per_window", [])
    turn_fx = turn_cfg.get("fixed", [])
    turn_feats = ([f"feat_{bn}{w}" for bn in turn_pw for w in windows
                   if f"feat_{bn}{w}" in all_features]
                  + [f"feat_{bn}" for bn in turn_fx if f"feat_{bn}" in all_features])
    if turn_feats:
        gfm["turnover"] = turn_feats

    # valuation
    val_cfg = feat_cfg.get("valuation_features", {})
    val_metrics = val_cfg.get("metrics", [])
    val_pw = val_cfg.get("per_metric_per_window", [])
    val_fx = val_cfg.get("per_metric_fixed", [])
    val_feats = ([f"feat_{m}_{s}{w}" for m in val_metrics for s in val_pw for w in windows
                  if f"feat_{m}_{s}{w}" in all_features]
                 + [f"feat_{m}_{s}" for m in val_metrics for s in val_fx
                    if f"feat_{m}_{s}" in all_features])
    if val_feats:
        gfm["valuation"] = val_feats

    # 收集已归组的因子, 剩余的放 _unknown
    assigned = set()
    for feats in gfm.values():
        assigned.update(feats)
    unknown = [f for f in all_features if f not in assigned]
    if unknown:
        gfm["_unknown"] = unknown

    return gfm


# ====================================================
# 组合入口：特征工程 + 中性化 (兼容旧调用)
# ====================================================
def run_feature_pipeline(
    cfg: dict | None = None,
    runtime_mode: str | None = None,
    progress_cb=None,
) -> tuple[pd.DataFrame, dict]:
    """
    全链路特征入口 (兼容旧 API):
      run_raw_feature_pipeline() -> run_neutralize_pipeline()

    等价于依次执行原始特征计算 + 中性化。
    """
    if cfg is None:
        cfg = load_config()
    raw_df, all_features, group_feature_map = run_raw_feature_pipeline(cfg, progress_cb=progress_cb)
    return run_neutralize_pipeline(
        cfg,
        raw_df,
        all_features,
        group_feature_map,
        runtime_mode=runtime_mode,
        progress_cb=progress_cb,
    )


# ====================================================
# 阶段入口：回测
# ====================================================
def run_backtest_pipeline(
    cfg: dict | None = None,
    output_dir: str | None = None,
    feature_set_id: str | None = None,
    label_set_id: str | None = None,
    runtime_mode: str | None = None,
    progress_cb=None,
) -> tuple[pd.DataFrame, dict]:
    """
    加载数据集 -> 回测 -> 评价 -> 标准化落盘，返回 (results_df, metrics)。

    v2 Phase E: 接受 feature_set_id / label_set_id 用于版本化数据加载 + 实验血缘。

    数据流:
      DatasetBuilder.build_train_dataset()  -> 组装训练/回测集
      run_walk_forward()                     -> WFA 回测
      evaluate()                             -> 绩效评价
      ExperimentStore                        -> 标准化落盘 (predictions, holdings, nav, metrics)
      experiment_run                         -> 血缘记录

    兼容模式: 如果 FeatureStore/LabelStore 不存在，回退到读取旧格式 merged parquet。
    """
    if cfg is None:
        cfg = load_config()

    # 进度回调辅助
    def _progress(pct: int, msg: str):
        if progress_cb:
            progress_cb(pct, msg)

    _progress(0, "初始化回测...")

    # 优先用新架构 DatasetBuilder，回退到旧路径
    feature_store = FeatureStore.from_config(cfg)
    label_store = LabelStore.from_config(cfg)

    if feature_store.exists and label_store.exists:
        _progress(5, "构建数据集...")
        builder = DatasetBuilder.from_config(cfg)
        df = builder.build_train_dataset(
            label_name=cfg["label"]["name"],
            feature_set_id=feature_set_id,
            label_set_id=label_set_id,
            runtime_mode=runtime_mode,
        )
        runtime_plan = df.attrs.get("dataset_runtime_plan", {})
        run_cfg = apply_runtime_mode_to_config(
            cfg,
            runtime_plan.get("mode", runtime_mode or "formal"),
            runtime_plan,
        )
        runtime_date_scope = runtime_plan.get("date_range") or "full"
        print(
            "[MODE] run_backtest_pipeline "
            f"runtime_mode={runtime_plan.get('mode', runtime_mode or 'formal')} "
            f"date_scope={runtime_date_scope} "
            f"feature_scope={runtime_plan.get('feature_count', len([c for c in df.columns if c.startswith('feat_')]))}"
            f"/{runtime_plan.get('available_feature_count', runtime_plan.get('feature_count', 0))} "
            f"backtest_overrides={runtime_plan.get('backtest_overrides', {})}"
        )
        print(f"[LOAD] [DatasetBuilder] 组装训练集: {df.shape[0]} 行 x {df.shape[1]} 列")
    else:
        # 回退：兼容旧流程
        feat_path = cfg["features"]["output"]
        print(f"[LOAD] [兼容] 加载旧格式特征矩阵: {feat_path}")
        df = pd.read_parquet(feat_path)
        df["date"] = pd.to_datetime(df["date"])
        run_cfg = apply_runtime_mode_to_config(cfg, runtime_mode or "formal")

    _progress(10, f"数据集就绪: {df.shape[0]} 行")
    features = [c for c in df.columns if c.startswith("feat_")]

    _progress(15, "开始 Walk-Forward 回测...")
    results = run_walk_forward(df, features, run_cfg, output_dir=output_dir)
    _progress(85, "回测完成，计算指标...")
    metrics = evaluate(results, run_cfg)

    # --------------------------------------------------
    # 标准化落盘：ExperimentStore
    # --------------------------------------------------
    _progress(90, "保存结果...")
    exp_dir = output_dir or "data/results"
    exp_store = ExperimentStore(exp_dir, cfg=run_cfg)
    exp_store.set_lineage(feature_set_id=feature_set_id, label_set_id=label_set_id)
    exp_store.register_run(run_cfg)

    if not results.empty:
        exp_store.save_predictions(results)

        holdings_df = build_holdings_from_predictions(results, cfg["backtest"]["top_k"])
        exp_store.save_holdings(holdings_df)

        nav_df = build_nav_from_metrics(metrics, results)
        if not nav_df.empty:
            exp_store.save_nav(nav_df)

        exp_store.save_metrics(metrics)
        exp_store.save_config(run_cfg)
        exp_store.finish_run("done")
    else:
        exp_store.finish_run("empty")

    _progress(100, "回测完成")
    return results, metrics


# ====================================================
# 阶段入口：因子分析
# ====================================================
def run_factor_analysis(
    cfg: dict | None = None,
    feature_set_id: str | None = None,
    label_set_id: str | None = None,
) -> dict:
    """加载特征矩阵 -> IC/ICIR/Decay 分析 -> 落盘"""
    if cfg is None:
        cfg = load_config()
    return run_ic_analysis(cfg, feature_set_id=feature_set_id, label_set_id=label_set_id)


# ====================================================
# 全链路编排
# ====================================================
def run_full_pipeline(
    cfg: dict | None = None,
    steps: list[str] | None = None,
) -> dict[str, Any]:
    """
    全链路主入口，按步骤顺序执行各阶段任务。

    steps 支持:
      - 'download'          -- 数据下载
      - 'etl'               -- 数据清洗合并
      - 'raw_feature'       -- 原始特征工程 (全量因子, 增量更新)
      - 'neutralize'        -- 因子筛选 + 截面中性化 + 标签
      - 'feature'           -- raw_feature + neutralize (兼容旧步骤名)
      - 'backtest'          -- 模型训练 + WFA 回测
      - 'factor_analysis'   -- IC/ICIR/Decay 分析
    """
    if cfg is None:
        cfg = load_config()
    if steps is None:
        steps = ["download", "etl", "raw_feature", "neutralize", "backtest", "factor_analysis"]

    results: dict[str, Any] = {}
    asset_ids: dict[str, str | None] = {}
    raw_df = None
    all_features = None
    group_feature_map = None

    if "download" in steps:
        run_downloader(cfg)

    if "etl" in steps:
        merge_and_clean(cfg)

    # 兼容旧步骤名 "feature" = raw_feature + neutralize
    if "feature" in steps:
        _, asset_ids = run_feature_pipeline(cfg)
    else:
        if "raw_feature" in steps:
            raw_df, all_features, group_feature_map = run_raw_feature_pipeline(cfg)

        if "neutralize" in steps:
            _, asset_ids = run_neutralize_pipeline(
                cfg, raw_df, all_features, group_feature_map,
            )

    if "backtest" in steps:
        results_df, metrics = run_backtest_pipeline(
            cfg,
            feature_set_id=asset_ids.get("feature_set_id"),
            label_set_id=asset_ids.get("label_set_id"),
        )
        results["backtest"] = results_df
        results["metrics"] = metrics

    if "factor_analysis" in steps:
        results["factor_analysis"] = run_factor_analysis(
            cfg,
            feature_set_id=asset_ids.get("feature_set_id"),
            label_set_id=asset_ids.get("label_set_id"),
        )

    return results


# ====================================================
# 独立标签更新入口 (Phase 2)
# ====================================================
def run_label_pipeline(cfg: dict | None = None, incremental: bool = True) -> dict:
    """
    独立标签更新入口。

    标签依赖未来数据 (horizon 天后)，因此存在合理滞后：
      - label_max <= daily_max - horizon

    Args:
        cfg: 配置字典
        incremental: 是否增量更新 (默认 True)

    Returns:
        {
            "status": "ok" | "skipped" | "error",
            "old_max": "2026-03-31",
            "new_max": "2026-04-12",
            "rows_added": N,
            "message": "..."
        }
    """
    import time

    start_time = time.time()

    if cfg is None:
        cfg = load_config()

    from src.data_layer.db import get_connection, table_exists, ingest_dataframe

    con = get_connection(cfg)

    # 1. 获取配置参数
    lbl_cfg = cfg["label"]
    horizon = lbl_cfg["horizon"]
    label_name = lbl_cfg["name"]
    label_method = lbl_cfg["method"]
    price_mode = get_price_mode(cfg)

    # 2. 获取 daily_bar 最新日期
    daily_max_row = con.execute("SELECT MAX(DATE(date)) FROM daily_bar").fetchone()
    if daily_max_row is None or daily_max_row[0] is None:
        return {"status": "error", "message": "daily_bar is empty"}
    daily_max = pd.to_datetime(daily_max_row[0]).normalize()

    # 3. 计算实际的 label 目标日期上限 (基于交易日，而非日历日)
    # 获取最后 horizon+1 个交易日，label 目标上限是第一个
    trading_days_df = con.execute(f"""
        SELECT DISTINCT DATE(date) as date
        FROM daily_bar
        ORDER BY date DESC
        LIMIT {horizon + 1}
    """).df()
    if len(trading_days_df) < horizon + 1:
        # 不够 horizon+1 个交易日，无法计算完整标签
        return {
            "status": "error",
            "message": f"Insufficient trading days ({len(trading_days_df)}) for horizon={horizon}",
        }

    trading_days_df["date"] = pd.to_datetime(trading_days_df["date"])
    trading_days = trading_days_df["date"].sort_values().reset_index(drop=True)
    # 最后一个交易日是 daily_max，label 目标上限是倒数第 horizon+1 个交易日
    # 因为 label 需要后 horizon 个交易日的数据
    target_label_max = trading_days.iloc[-(horizon + 1)]

    # 4. 获取 label_wide 当前状态
    old_label_max = None
    if table_exists(cfg, "label_wide"):
        row = con.execute("SELECT MAX(DATE(date)) FROM label_wide").fetchone()
        if row and row[0]:
            old_label_max = pd.to_datetime(row[0]).normalize()

    # 5. 判断是否需要更新
    if old_label_max is not None and old_label_max.normalize() == target_label_max.normalize():
        return {
            "status": "skipped",
            "old_max": str(old_label_max.date()),
            "new_max": str(old_label_max.date()),
            "rows_added": 0,
            "message": f"label_wide already up-to-date ({old_label_max.date()})",
        }

    # 6. 计算重算窗口起点 (考虑边界效应)
    # 标签依赖未来数据，需要从 old_max - horizon - 安全边际 开始重算
    safety_margin = 2  # 额外安全边际 (交易日)
    if old_label_max is not None:
        recalc_start = old_label_max - pd.Timedelta(days=horizon + safety_margin)
    else:
        # 全量计算：从 daily_bar 最小日期开始
        min_row = con.execute("SELECT MIN(DATE(date)) FROM daily_bar").fetchone()
        recalc_start = pd.to_datetime(min_row[0]).normalize()

    recalc_start_str = recalc_start.strftime("%Y-%m-%d")
    target_max_str = target_label_max.strftime("%Y-%m-%d")
    daily_max_str = daily_max.strftime("%Y-%m-%d")

    print(f"[LABEL] 标签更新开始:")
    print(f"  daily_bar.max = {daily_max.date()}")
    print(f"  old_label_max = {old_label_max.date() if old_label_max else 'None'}")
    print(f"  target_label_max = {target_label_max.date()} (基于交易日，horizon={horizon})")
    print(f"  recalc_start = {recalc_start.date()} (考虑边界效应)")

    # 7. 加载所需数据
    # 标签计算需要: date, code, raw_pctChg (或 raw_close)
    # 需要加载到 daily_max 而非 target_label_max，因为标签依赖未来 horizon 天数据
    sql = f"""
        SELECT
            db.date,
            db.code,
            db.raw_open,
            db.raw_high,
            db.raw_low,
            db.raw_close,
            db.raw_pctChg,
            db.fwd_factor,
            db.bwd_factor,
            db.industry
        FROM daily_bar db
        WHERE DATE(db.date) >= DATE('{recalc_start_str}')
          AND DATE(db.date) <= DATE('{daily_max_str}')
        ORDER BY db.code, db.date
    """
    df = con.execute(sql).df()
    if df.empty:
        return {
            "status": "skipped",
            "old_max": str(old_label_max.date()) if old_label_max else None,
            "new_max": str(old_label_max.date()) if old_label_max else None,
            "rows_added": 0,
            "message": "No data in calculation window",
        }

    df["date"] = pd.to_datetime(df["date"])
    print(f"  加载 daily_bar 数据: {len(df):,} 行")

    # 8. 生成标签
    print(f"[LABEL] 生成标签 ({label_name}, method={label_method}, horizon={horizon})...")

    adjusted_df = apply_price_mode(df, price_mode)
    try:
        label_values = compute_label_values(adjusted_df, label_method, horizon)
    except ValueError:
        return {
            "status": "error",
            "message": f"Unsupported label method: {label_method}",
        }

    df[label_name] = label_values

    # 9. 清理无标签行 (未来数据不足)
    before_drop = len(df)
    df = df.dropna(subset=[label_name]).reset_index(drop=True)
    print(f"  清理无标签行: {before_drop:,} -> {len(df):,}")

    # 10. 只保留到 target_label_max 日期
    before_filter = len(df)
    df = df[df["date"].dt.normalize() <= target_label_max].reset_index(drop=True)
    print(f"  过滤到目标日期: {before_filter:,} -> {len(df):,} (<= {target_label_max.date()})")

    # 11. 准备输出 (只保留 date, code, label)
    label_cols = [c for c in df.columns if c.startswith("label_")]
    if label_name not in label_cols:
        label_cols.append(label_name)
    out_cols = ["date", "code"] + label_cols
    out_df = df[[c for c in out_cols if c in df.columns]].copy()
    out_df["date"] = out_df["date"].dt.strftime("%Y-%m-%d")
    out_df = out_df.sort_values(["code", "date"]).reset_index(drop=True)

    # 12. 写入 label_wide (使用 upsert 模式)
    if old_label_max is not None:
        # 增量更新：先删除旧数据中重叠的部分
        con.execute(f"""
            DELETE FROM label_wide
            WHERE DATE(date) >= DATE('{recalc_start_str}')
        """)
        # 然后追加新数据
        ingest_dataframe(cfg, "label_wide", out_df, mode="append")
    else:
        # 全量创建
        ingest_dataframe(cfg, "label_wide", out_df, mode="replace")

    # 13. 验证结果
    new_max_row = con.execute("SELECT MAX(DATE(date)), COUNT(*) FROM label_wide").fetchone()
    new_max = pd.to_datetime(new_max_row[0]).normalize() if new_max_row[0] else None
    new_count = new_max_row[1] if new_max_row else 0

    elapsed = time.time() - start_time

    print(f"[LABEL] 标签更新完成:")
    print(f"  new_max = {new_max.date() if new_max else 'None'}")
    print(f"  total_rows = {new_count:,}")
    print(f"  elapsed = {elapsed:.1f}s")

    return {
        "status": "ok",
        "old_max": str(old_label_max.date()) if old_label_max else None,
        "new_max": str(new_max.date()) if new_max else None,
        "rows_added": len(out_df),
        "message": f"Label updated from {old_label_max.date() if old_label_max else 'None'} to {new_max.date() if new_max else 'None'}",
    }


# ====================================================
# 数据新鲜度校验 (Phase 2)
# ====================================================
def _check_data_freshness(cfg: dict, run_prediction: bool = False) -> dict:
    """
    校验数据新鲜度。

    规则:
      - 规则 1: feature_max == daily_max (特征与日线同步)
      - 规则 2: label_max <= daily_max - horizon (标签合理滞后)
      - 规则 3: 若 run_prediction=True, pred_max <= label_max (预测依赖标签)

    Returns:
        {
            "status": "ok" | "warning" | "error",
            "daily_bar": {"max_date": "...", "count": N},
            "feature_wide": {"max_date": "...", "count": N, "check": "ok" | "fail", "reason": "..."},
            "label_wide": {"max_date": "...", "count": N, "check": "ok" | "fail", "reason": "..."},
            "predictions": {...} | None,
        }
    """
    from src.data_layer.db import get_connection, table_exists

    con = get_connection(cfg)
    horizon = cfg["label"]["horizon"]

    result = {
        "status": "ok",
        "daily_bar": {},
        "feature_wide": {},
        "label_wide": {},
        "predictions": None,
    }

    # 1. 获取 daily_bar 状态
    row = con.execute("SELECT MAX(DATE(date)), COUNT(*) FROM daily_bar").fetchone()
    daily_max = pd.to_datetime(row[0]).normalize() if row[0] else None
    daily_count = row[1] if row else 0
    result["daily_bar"] = {"max_date": str(daily_max.date()) if daily_max else None, "count": daily_count}

    # 2. 获取 feature_wide 状态
    if table_exists(cfg, "feature_wide"):
        row = con.execute("SELECT MAX(DATE(date)), COUNT(*) FROM feature_wide").fetchone()
        feature_max = pd.to_datetime(row[0]).normalize() if row[0] else None
        feature_count = row[1] if row else 0

        # 规则 1: feature_max == daily_max
        check_ok = feature_max is not None and daily_max is not None and feature_max.normalize() == daily_max.normalize()
        result["feature_wide"] = {
            "max_date": str(feature_max.date()) if feature_max else None,
            "count": feature_count,
            "check": "ok" if check_ok else "fail",
            "reason": None if check_ok else f"feature_max ({feature_max.date() if feature_max else 'None'}) != daily_max ({daily_max.date() if daily_max else 'None'})",
        }
        if not check_ok:
            result["status"] = "warning"
    else:
        result["feature_wide"] = {"max_date": None, "count": 0, "check": "fail", "reason": "feature_wide table not found"}
        result["status"] = "error"

    # 3. 获取 label_wide 状态
    if table_exists(cfg, "label_wide"):
        row = con.execute("SELECT MAX(DATE(date)), COUNT(*) FROM label_wide").fetchone()
        label_max = pd.to_datetime(row[0]).normalize() if row[0] else None
        label_count = row[1] if row else 0

        # 规则 2: label_max 应等于基于交易日计算的目标日期
        # 获取最后 horizon+1 个交易日，目标日期是倒数第 horizon+1 个
        trading_days_df = con.execute(f"""
            SELECT DISTINCT DATE(date) as date
            FROM daily_bar
            ORDER BY date DESC
            LIMIT {horizon + 1}
        """).df()
        if len(trading_days_df) >= horizon + 1:
            trading_days_df["date"] = pd.to_datetime(trading_days_df["date"])
            trading_days = trading_days_df["date"].sort_values().reset_index(drop=True)
            target_label_max = trading_days.iloc[-(horizon + 1)]
            # label_max 应该等于 target_label_max (精确同步)
            check_ok = label_max is not None and label_max.normalize() == target_label_max.normalize()
            reason = None if check_ok else f"label_max ({label_max.date() if label_max else 'None'}) != target ({target_label_max.date()})"
        else:
            check_ok = False
            reason = f"Insufficient trading days for horizon={horizon}"

        result["label_wide"] = {
            "max_date": str(label_max.date()) if label_max else None,
            "count": label_count,
            "check": "ok" if check_ok else "fail",
            "reason": reason,
        }
        if not check_ok:
            result["status"] = "warning"
    else:
        result["label_wide"] = {"max_date": None, "count": 0, "check": "fail", "reason": "label_wide table not found"}
        result["status"] = "error"

    # 4. 预测表检查 (可选)
    if run_prediction and table_exists(cfg, "predictions"):
        row = con.execute("SELECT MAX(DATE(date)), COUNT(*) FROM predictions").fetchone()
        pred_max = pd.to_datetime(row[0]).normalize() if row[0] else None
        pred_count = row[1] if row else 0

        # 规则 3: pred_max <= label_max
        label_max_str = result["label_wide"].get("max_date")
        label_max_dt = pd.to_datetime(label_max_str) if label_max_str else None
        check_ok = pred_max is not None and label_max_dt is not None and pred_max.normalize() <= label_max_dt.normalize()
        result["predictions"] = {
            "max_date": str(pred_max.date()) if pred_max else None,
            "count": pred_count,
            "check": "ok" if check_ok else "fail",
            "reason": None if check_ok else f"pred_max ({pred_max.date() if pred_max else 'None'}) > label_max ({label_max_str})",
        }
        if not check_ok:
            result["status"] = "warning"

    return result


def _print_freshness_report(freshness: dict, horizon: int) -> None:
    """打印新鲜度校验报告"""
    print("\n=== 数据新鲜度校验 ===")

    daily = freshness.get("daily_bar", {})
    print(f"daily_bar     {daily.get('max_date', 'N/A')}")

    feature = freshness.get("feature_wide", {})
    feature_check = feature.get("check", "N/A")
    feature_reason = feature.get("reason")
    feature_status = f"  {'OK' if feature_check == 'ok' else 'FAIL'} ({feature_reason})" if feature_reason else f"  {'OK' if feature_check == 'ok' else 'FAIL'}"
    print(f"feature_wide  {feature.get('max_date', 'N/A')}{feature_status}")

    label = freshness.get("label_wide", {})
    label_check = label.get("check", "N/A")
    label_reason = label.get("reason")
    label_status = f"  {'OK' if label_check == 'ok' else 'FAIL'} (合理滞后 horizon={horizon})" if label_check == "ok" else f"  {'FAIL'} ({label_reason})"
    print(f"label_wide    {label.get('max_date', 'N/A')}{label_status}")

    pred = freshness.get("predictions")
    if pred:
        pred_check = pred.get("check", "N/A")
        pred_reason = pred.get("reason")
        pred_status = f"  {'OK' if pred_check == 'ok' else 'FAIL'} ({pred_reason})" if pred_reason else f"  {'OK' if pred_check == 'ok' else 'FAIL'}"
        print(f"predictions   {pred.get('max_date', 'N/A')}{pred_status}")
    else:
        print("predictions   (skipped)")

    status = freshness.get("status", "unknown")
    print(f"\nSTATUS: {status.upper()}")


# ====================================================
# 统一每日更新入口 (Phase 2)
# ====================================================
def run_daily_update(cfg: dict | None = None, run_prediction: bool = False) -> dict:
    """
    统一每日更新入口。

    执行顺序：
      1. daily_bar 更新 (调用现有 API 下载逻辑)
      2. feature_wide 更新 (调用现有 run_raw_feature_pipeline)
      3. label_wide 更新 (调用新 run_label_pipeline)
      4. (可选) predictions 更新

    Args:
        cfg: 配置字典
        run_prediction: 是否更新预测

    Returns:
        {
            "status": "ok" | "partial" | "error",
            "steps": {
                "daily_bar": {"status": "ok", "max_date": "..."},
                "feature_wide": {"status": "ok", "max_date": "..."},
                "label_wide": {"status": "ok", "max_date": "..."},
                "predictions": {"status": "skipped", ...}
            },
            "freshness_check": {...},
            "elapsed_seconds": N
        }
    """
    import time

    start_time = time.time()

    if cfg is None:
        cfg = load_config()

    result = {
        "status": "ok",
        "steps": {
            "daily_bar": {"status": "pending"},
            "feature_wide": {"status": "pending"},
            "label_wide": {"status": "pending"},
            "predictions": {"status": "pending"},
        },
        "freshness_check": None,
        "elapsed_seconds": 0,
    }

    horizon = cfg["label"]["horizon"]

    # Step 1: daily_bar 更新 (调用 API 下载)
    print("\n[STEP 1] daily_bar 更新...")
    try:
        from src.data_hub import run_downloader, merge_and_clean

        run_downloader(cfg)
        merge_and_clean(cfg)

        from src.data_layer.db import get_connection
        con = get_connection(cfg)
        row = con.execute("SELECT MAX(DATE(date)), COUNT(*) FROM daily_bar").fetchone()
        result["steps"]["daily_bar"] = {
            "status": "ok",
            "max_date": row[0] if row else None,
            "count": row[1] if row else 0,
        }
        print(f"  daily_bar max_date = {row[0]}, count = {row[1]:,}")
    except Exception as e:
        result["steps"]["daily_bar"] = {"status": "error", "message": str(e)}
        result["status"] = "error"
        print(f"  ERROR: {e}")
        return _finalize_update(result, start_time)

    # Step 2: feature_wide 更新
    print("\n[STEP 2] feature_wide 更新...")
    try:
        raw_df, _, _ = run_raw_feature_pipeline(cfg)

        from src.data_layer.db import get_connection
        con = get_connection(cfg)
        row = con.execute("SELECT MAX(DATE(date)), COUNT(*) FROM feature_wide").fetchone()
        result["steps"]["feature_wide"] = {
            "status": "ok",
            "max_date": row[0] if row else None,
            "count": row[1] if row else 0,
        }
        print(f"  feature_wide max_date = {row[0]}, count = {row[1]:,}")
    except Exception as e:
        result["steps"]["feature_wide"] = {"status": "error", "message": str(e)}
        result["status"] = "error"
        print(f"  ERROR: {e}")
        return _finalize_update(result, start_time)

    # Step 3: label_wide 更新
    print("\n[STEP 3] label_wide 更新...")
    try:
        label_result = run_label_pipeline(cfg, incremental=True)
        result["steps"]["label_wide"] = {
            "status": label_result.get("status", "ok"),
            "old_max": label_result.get("old_max"),
            "new_max": label_result.get("new_max"),
            "rows_added": label_result.get("rows_added", 0),
            "message": label_result.get("message"),
        }
        print(f"  label_wide status = {label_result.get('status')}, new_max = {label_result.get('new_max')}")
    except Exception as e:
        result["steps"]["label_wide"] = {"status": "error", "message": str(e)}
        result["status"] = "error"
        print(f"  ERROR: {e}")
        return _finalize_update(result, start_time)

    # Step 4: predictions 更新 (可选)
    if run_prediction:
        print("\n[STEP 4] predictions 更新...")
        try:
            # 调用回测流程生成预测
            # 这里暂时标记为 skipped，后续可扩展
            result["steps"]["predictions"] = {"status": "skipped", "message": "Not implemented yet"}
        except Exception as e:
            result["steps"]["predictions"] = {"status": "error", "message": str(e)}
            print(f"  ERROR: {e}")
    else:
        result["steps"]["predictions"] = {"status": "skipped", "message": "run_prediction=False"}

    # Step 5: freshness 校验
    print("\n[STEP 5] 数据新鲜度校验...")
    freshness = _check_data_freshness(cfg, run_prediction)
    result["freshness_check"] = freshness
    _print_freshness_report(freshness, horizon)

    # 根据校验结果设置最终状态
    if freshness.get("status") == "error":
        result["status"] = "error"
    elif freshness.get("status") == "warning":
        result["status"] = "partial"

    return _finalize_update(result, start_time)


def _finalize_update(result: dict, start_time: float) -> dict:
    """完成更新，计算耗时"""
    import time
    result["elapsed_seconds"] = round(time.time() - start_time, 1)
    return result


# ====================================================
# 分块特征重建入口
# ====================================================
def run_feature_chunk_rebuild(
    cfg: dict | None = None,
    chunk_days: int = 256,
    warmup_days: int = 70,
    resume: bool = True,
    publish: bool = False,
) -> dict:
    """
    分块重建原始特征矩阵。

    用于大数据量场景，避免一次性全量加载导致内存溢出。
    支持:
      - 分段计算
      - 分段落盘
      - 断点续跑
      - 原子发布

    Args:
        cfg: 配置字典 (None 则自动加载)
        chunk_days: 每个chunk的天数 (默认256，约1年交易日)
        warmup_days: 预热期天数 (默认70，用于滚动窗口计算)
        resume: 是否从上次中断处继续
        publish: 是否立即发布到feature_wide表

    Returns:
        dict with status, total_chunks, total_rows, etc.
    """
    if cfg is None:
        cfg = load_config()

    from src.feature_chunk_builder import run_feature_chunk_rebuild as _run
    return _run(cfg, chunk_days, warmup_days, resume, publish)


def publish_feature_chunks(cfg: dict | None = None) -> dict:
    """
    发布已完成的chunk到feature_wide表。

    用于在run_feature_chunk_rebuild(publish=False)后单独执行发布。
    """
    if cfg is None:
        cfg = load_config()

    from src.feature_chunk_builder import publish_feature_chunks as _publish
    return _publish(cfg)


if __name__ == "__main__":
    cfg = load_config()
    # 默认: 全量特征 -> 中性化 -> 回测
    raw_df, all_features, gfm = run_raw_feature_pipeline(cfg)
    _, asset_ids = run_neutralize_pipeline(cfg, raw_df, all_features, gfm)
    results_df, metrics = run_backtest_pipeline(
        cfg,
        feature_set_id=asset_ids.get("feature_set_id"),
        label_set_id=asset_ids.get("label_set_id"),
    )
