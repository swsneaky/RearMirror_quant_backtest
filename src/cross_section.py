"""
截面处理器 -- MAD 去极值 + 行业中性化 + Z-Score 标准化
铁律四：截面三步曲不可省略，小样本保护必须到位
"""
from __future__ import annotations

import math
import time
from typing import Callable, Optional

import numpy as np
import pandas as pd

from src.runtime_modes import resolve_runtime_mode


def _mad_clip(x: pd.Series, multiplier: float) -> pd.Series:
    """MAD 去极值"""
    if x.notna().sum() == 0:
        return x
    median = x.median()
    mad = np.abs(x - median).median()
    bound = multiplier * mad
    return x.clip(lower=median - bound, upper=median + bound)


def _process_daily_frame(
    daily_df: pd.DataFrame,
    features: list[str],
    mad_mult: float,
    min_ind: int,
    eps: float,
) -> pd.DataFrame:
    for col in features:
        clipped = _mad_clip(daily_df[col], mad_mult)
        if clipped.notna().sum() == 0:
            daily_df[col] = 0.0
            continue

        ind_counts = daily_df.groupby("industry")[col].transform("count")
        ind_mean = clipped.groupby(daily_df["industry"]).transform("mean")
        neutralized = np.where(ind_counts >= min_ind, clipped - ind_mean, clipped)
        neutralized = pd.Series(neutralized, index=daily_df.index)
        valid_neutralized = neutralized.dropna()
        if valid_neutralized.empty:
            daily_df[col] = 0.0
            continue

        std_val = valid_neutralized.std()
        if pd.notna(std_val) and std_val > eps:
            daily_df[col] = (neutralized - valid_neutralized.mean()) / std_val
        else:
            daily_df[col] = 0.0
    return daily_df


def _chunk_dates(dates: list, chunk_size: int) -> list[list]:
    return [dates[i:i + chunk_size] for i in range(0, len(dates), chunk_size)]


def _normalize_date_str(value) -> str:
    return str(pd.Timestamp(value))


def _validate_chunk_frame(
    chunk_df: pd.DataFrame,
    expected_dates: list,
    expected_columns: list[str],
    chunk_index: int,
) -> dict:
    if chunk_df.empty:
        raise ValueError(f"中性化第 {chunk_index} 个时间块结果为空，无法继续合并。")

    if list(chunk_df.columns) != expected_columns:
        raise ValueError(
            f"中性化第 {chunk_index} 个时间块列集发生漂移："
            f"expected={expected_columns}, actual={list(chunk_df.columns)}"
        )

    actual_dates = list(pd.Index(chunk_df["date"]).drop_duplicates())
    if actual_dates != expected_dates:
        raise ValueError(
            f"中性化第 {chunk_index} 个时间块日期顺序异常："
            f"expected={[ _normalize_date_str(d) for d in expected_dates ]}, "
            f"actual={[ _normalize_date_str(d) for d in actual_dates ]}"
        )

    if {"date", "code"}.issubset(chunk_df.columns):
        pk_dup = int(chunk_df.duplicated(subset=["date", "code"]).sum())
        if pk_dup:
            raise ValueError(
                f"中性化第 {chunk_index} 个时间块出现主键重复: pk_dup={pk_dup}"
            )
    else:
        pk_dup = 0

    return {
        "chunk_index": chunk_index,
        "date_start": _normalize_date_str(expected_dates[0]),
        "date_end": _normalize_date_str(expected_dates[-1]),
        "date_count": len(expected_dates),
        "row_count": int(len(chunk_df)),
        "pk_dup": pk_dup,
        "columns": list(chunk_df.columns),
    }


def _validate_chunk_sequence(
    manifests: list[dict],
    expected_columns: list[str],
) -> None:
    if not manifests:
        raise ValueError("未生成任何中性化时间块 manifest。")

    for manifest in manifests:
        if manifest["columns"] != expected_columns:
            raise ValueError(
                f"中性化块 {manifest['chunk_index']} 列集与输入不一致。"
            )

    for prev, curr in zip(manifests, manifests[1:]):
        if prev["date_end"] >= curr["date_start"]:
            raise ValueError(
                "中性化块间日期边界重叠或未严格递增："
                f"{prev['date_end']} -> {curr['date_start']}"
            )


def cross_sectional_process(
    df: pd.DataFrame,
    features: list[str],
    cfg: dict,
    progress_cb: Optional[Callable[[int, str], None]] = None,
    *,
    runtime_mode: str | None = None,
    chunk_size: int | None = None,
) -> pd.DataFrame:
    """
    按日期截面执行三步处理：MAD -> 行业中性化 -> Z-Score

    在不改变逐日业务语义的前提下，按固定日期块分段执行并做块级校验，
    避免把所有日结果长期累计到单个大列表后再黑箱收尾。

    Args:
        progress_cb: 可选进度回调 (pct: int, message: str)
        runtime_mode: formal / shared_machine，仅影响执行块预算，不改变业务语义
        chunk_size: 显式覆盖单块日期数，主要供测试使用
    """
    cs_cfg = cfg["cross_section"]
    mad_mult = cs_cfg["mad_multiplier"]
    min_ind = cs_cfg["min_industry_stocks"]
    eps = cs_cfg["zscore_eps"]

    mode_name, mode_cfg = resolve_runtime_mode(cfg, runtime_mode)

    dates = sorted(df["date"].unique())
    total_dates = len(dates)
    if total_dates == 0:
        out = df.copy()
        out.attrs["cross_section_segment_plan"] = {
            "runtime_mode": mode_name,
            "chunk_days": 0,
            "segment_count": 0,
            "segments": [],
        }
        return out

    resolved_chunk_size = int(chunk_size or mode_cfg.get("neutralize_chunk_days") or total_dates)
    resolved_chunk_size = max(1, min(resolved_chunk_size, total_dates))
    date_chunks = _chunk_dates(dates, resolved_chunk_size)
    total_segments = len(date_chunks)
    expected_columns = list(df.columns)

    print(
        "[PROC] 正在执行截面 MAD + 行业中性化 + Z-Score 标准化..."
        f" runtime_mode={mode_name} chunk_days={resolved_chunk_size} "
        f"segments={total_segments}",
        flush=True,
    )
    t0 = time.time()

    from tqdm import tqdm

    segment_frames: list[pd.DataFrame] = []
    manifests: list[dict] = []
    processed_dates = 0

    for seg_idx, chunk_dates in enumerate(date_chunks, start=1):
        seg_t0 = time.time()
        chunk_results = []
        print(
            "[SEG] 开始处理中性化时间块 "
            f"{seg_idx}/{total_segments}: "
            f"{_normalize_date_str(chunk_dates[0])} -> {_normalize_date_str(chunk_dates[-1])} "
            f"({len(chunk_dates)} 天)",
            flush=True,
        )

        for d in tqdm(chunk_dates, desc=f"截面中性化 chunk {seg_idx}/{total_segments}", unit="天"):
            daily_df = df.loc[df["date"] == d].copy()
            chunk_results.append(
                _process_daily_frame(daily_df, features, mad_mult, min_ind, eps)
            )

            processed_dates += 1
            if progress_cb and (processed_dates % 50 == 0 or processed_dates == total_dates):
                pct = int(processed_dates / total_dates * 100)
                progress_cb(
                    pct,
                    f"截面中性化 {processed_dates}/{total_dates} 天 (chunk {seg_idx}/{total_segments})",
                )

        chunk_df = pd.concat(chunk_results, ignore_index=True)
        manifest = _validate_chunk_frame(chunk_df, chunk_dates, expected_columns, seg_idx)
        manifests.append(manifest)
        segment_frames.append(chunk_df)

        print(
            "[SEG] 时间块完成 "
            f"{seg_idx}/{total_segments}: "
            f"rows={manifest['row_count']:,} pk_dup={manifest['pk_dup']} "
            f"elapsed={time.time() - seg_t0:.1f}s",
            flush=True,
        )

    _validate_chunk_sequence(manifests, expected_columns)
    print(
        f"[PROC] 中性化块级校验完成，正在合并 {total_segments} 个时间块结果...",
        flush=True,
    )
    df_out = pd.concat(segment_frames, ignore_index=True)
    print(
        f"[OK] 截面处理完成！耗时: {time.time() - t0:.1f} 秒，输出形状: "
        f"{df_out.shape[0]:,} 行 x {df_out.shape[1]} 列",
        flush=True,
    )
    df_out.attrs["cross_section_segment_plan"] = {
        "runtime_mode": mode_name,
        "chunk_days": resolved_chunk_size,
        "segment_count": total_segments,
        "segments": manifests,
    }
    return df_out
