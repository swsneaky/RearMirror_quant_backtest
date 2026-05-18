"""
特征工厂 -- 通过注册表动态调度因子函数
铁律二：所有输出因子列名带 feat_ 前缀
铁律三：float32 + sort + parquet
铁律四：窗口严格来自 config (默认 [5,10,20,30,60])

v2 升级:
  - 从 CanonicalStore 读数据 (不再直接读 parquet)
  - 从 registry.FactorMeta 获取 input_cols (消除硬编码)
  - 注册因子定义到 SQLite factor_definitions 表

v3 升级:
  - 因子组级断点续传: 每完成一个因子组即 checkpoint
  - 进度回调: 可选的 progress_cb 用于向 TaskStore 报告进度

扩展方式: 在 src/factors/ 下新建 .py, 用 @registry.register_factor 装饰
"""
import json
import logging
import os
import time
from typing import Callable, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

from src.registry import registry
from src.price_mode import apply_price_mode, get_price_mode
import src.factors  # noqa: F401  触发内置因子注册


def validate_raw_schema(df: pd.DataFrame, required_columns: list[str]) -> None:
    """
    校验原始数据表是否包含所有必要的 raw_ 前缀列。
    缺失则抛出 ValueError 并终止。
    """
    missing = [col for col in required_columns if col not in df.columns]
    if missing:
        raise ValueError(f"原始数据缺失必要字段: {missing}")


def _get_required_raw_cols(name: str) -> list[str]:
    """
    从 registry FactorMeta 获取因子组所需原始列。
    如果因子未声明 FactorMeta, 回退到硬编码 (兼容旧因子)。
    """
    meta = registry.get_factor_meta(name)
    if meta is not None:
        return list(meta.input_cols)

    # legacy fallback
    _legacy = {
        'kline': ["raw_open", "raw_close", "raw_high", "raw_low", "raw_volume"],
        'rolling': ["raw_close", "raw_high", "raw_low", "raw_volume", "raw_pctChg"],
        'rolling_ext': ["raw_close", "raw_high", "raw_low", "raw_volume", "raw_pctChg"],
        'technical': ["raw_close", "raw_high", "raw_low", "raw_volume", "raw_amount", "raw_pctChg"],
        'turnover': ["raw_turn"],
        'valuation': ["raw_peTTM", "raw_pbMRQ", "raw_psTTM", "raw_pcfNcfTTM"],
    }
    return _legacy.get(name, [])


def _sync_factor_definitions(cfg: dict, activated_factors: list[str], windows: list[int]) -> list[str]:
    """
    将当前激活因子的定义同步到 SQLite factor_definitions 表。
    返回 factor_id 列表 (供 feature_set_factors 登记用)。
    """
    factor_ids = []
    try:
        from src.data_layer.db import register_factor_def
        from src.data_layer.asset_id import make_factor_id

        for name in activated_factors:
            meta = registry.get_factor_meta(name)
            code_hash = registry.get_factor_code_hash(name)
            if not code_hash:
                continue

            factor_id = make_factor_id(name, code_hash)
            input_cols = meta.input_cols if meta else _get_required_raw_cols(name)
            output_cols = meta.output_cols if meta else []

            register_factor_def(
                cfg,
                factor_id=factor_id,
                factor_group=name,
                code_hash=code_hash,
                input_cols=input_cols,
                output_cols=output_cols,
                windows=windows if (meta and meta.windowed) else None,
                description=meta.description if meta else "",
            )
            factor_ids.append(factor_id)
    except Exception as exc:
        logger.warning("因子定义同步到 SQLite 失败 (不影响主流程): %s", exc)

    return factor_ids


def _get_process_rss_mb() -> float:
    """获取当前进程 RSS 内存 (MB)，获取失败返回 -1"""
    try:
        import psutil
        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except Exception:
        pass
    # fallback: Windows kernel32
    try:
        import ctypes
        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong),
                         ("PageFaultCount", ctypes.c_ulong),
                         ("PeakWorkingSetSize", ctypes.c_size_t),
                         ("WorkingSetSize", ctypes.c_size_t),
                         ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                         ("QuotaPagedPoolUsage", ctypes.c_size_t),
                         ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                         ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                         ("PagefileUsage", ctypes.c_size_t),
                         ("PeakPagefileUsage", ctypes.c_size_t)]
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        if ctypes.windll.psapi.GetProcessMemoryInfo(
            ctypes.windll.kernel32.GetCurrentProcess(),
            ctypes.byref(counters), counters.cb,
        ):
            return counters.WorkingSetSize / (1024 * 1024)
    except Exception:
        pass
    return -1.0


def build_alpha158(
    cfg: dict,
    progress_cb: Optional[Callable[[int, str], None]] = None,
    factor_groups: list[str] | None = None,
    input_df: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, list[str], dict[str, list[str]]]:
    """
    从 CanonicalStore 加载量价数据, 通过注册表调度因子函数生成因子矩阵。
    输出列名遵守 feat_ 前缀协议。

    支持按需因子组计算与增量数据切片:
      - factor_groups: 仅计算指定的因子组 (默认使用 active_factors 配置)
      - input_df: 外部提供的数据切片 (跳过 CanonicalStore 加载, 用于增量模式)

    **断点续传**: 全量计算时, 每完成一个因子组 checkpoint 到磁盘;
    增量模式 (input_df 非空) 跳过 checkpoint。

    Args:
        cfg: 配置字典
        progress_cb: 可选进度回调 (pct: int, message: str)
        factor_groups: 要计算的因子组列表 (None=使用 active_factors 配置)
        input_df: 外部数据切片 (None=从 CanonicalStore 加载全量)

    Returns
    -------
    df : 包含因子的 DataFrame
    all_features : 全部 feat_ 列名列表
    group_feature_map : {组名: [feat_列名, ...]} 映射
    """
    feat_cfg = cfg["features"]
    windows = feat_cfg["windows"]
    f32 = cfg["engine"]["float_dtype"]
    is_incremental = input_df is not None

    # ── 数据加载 ──
    if input_df is not None:
        if progress_cb:
            progress_cb(2, "使用外部数据切片 (增量模式)...")
        print(f"[1/2] 增量模式: 使用外部数据切片 ({len(input_df):,} 行)")
        df = input_df.copy()
        # 增量模式仍需行业映射
        if "industry" not in df.columns:
            try:
                from src.data_layer.canonical import CanonicalStore
                store = CanonicalStore.from_config(cfg)
                ind_df = store.load_industry()
                df = df.merge(ind_df, on="code", how="left")
                df["industry"] = df["industry"].fillna("Unknown")
            except Exception as exc:
                logger.warning("增量模式行业映射加载失败: %s", exc)
                df["industry"] = "Unknown"
    else:
        if progress_cb:
            progress_cb(2, "加载底层量价矩阵与行业映射表...")
        print("[1/2] 正在加载底层量价矩阵与行业映射表...")
        try:
            from src.data_layer.canonical import CanonicalStore
            store = CanonicalStore.from_config(cfg)
            df = store.load_daily()
            ind_df = store.load_industry()
            print("  [SRC] 数据源: CanonicalStore (SQLite/Parquet)")
        except Exception as exc:
            logger.warning("CanonicalStore 加载失败, 回退到 raw parquet: %s", exc)
            etl = cfg["etl"]
            df = pd.read_parquet(etl["raw_output"])
            ind_df = pd.read_parquet(etl["industry_map"])

        # 仅在 df 尚无 industry 列时 merge; load_daily() 已含 industry 时跳过
        if "industry" not in df.columns:
            df = df.merge(ind_df, on="code", how="left")
        df["industry"] = df["industry"].fillna("Unknown")

    df = df.sort_values(["code", "date"]).reset_index(drop=True)

    # 次新股过滤 (仅全量模式; 增量模式由调用方保证数据已过滤)
    if not is_incremental:
        min_days = feat_cfg.get("min_listing_days", 60)
        df["_listing_days"] = df.groupby("code").cumcount()
        df = df[df["_listing_days"] >= min_days].copy()

    # 确保 isST / tradestatus 列存在 (兼容旧数据)
    if "isST" not in df.columns:
        df["isST"] = 0
    if "tradestatus" not in df.columns:
        df["tradestatus"] = 1

    price_mode = get_price_mode(cfg)
    df = apply_price_mode(df, price_mode)

    # 复权价 (内部计算用辅助列, 以 _ 开头)
    df["_close_adj"] = df["adj_close"]
    df["_open_adj"] = df["adj_open"]
    df["_high_adj"] = df["adj_high"]
    df["_low_adj"] = df["adj_low"]
    df["_vol_log"] = np.log1p(df["raw_volume"])

    grouped = df.groupby("code")
    all_features: list[str] = []
    group_feature_map: dict[str, list[str]] = {}

    # ── 确定要计算的因子组 ──
    all_registered = registry.list_factors()
    if not all_registered:
        raise ValueError("没有已注册的因子组！请检查 src/factors/ 目录。")

    if factor_groups is not None:
        # 显式指定: 过滤掉未注册的组
        target_groups = [g for g in factor_groups if g in all_registered]
        skipped = [g for g in factor_groups if g not in all_registered]
        if skipped:
            logger.warning("因子组未注册, 已跳过: %s", skipped)
    else:
        # 默认: 使用 active_factors 配置; 回退到全量 (兼容旧行为)
        active = feat_cfg.get("active_factors")
        if active:
            target_groups = [g for g in active if g in all_registered]
        else:
            target_groups = list(all_registered)

    if not target_groups:
        raise ValueError(
            f"无有效因子组！active_factors={feat_cfg.get('active_factors')}, "
            f"已注册={all_registered}"
        )

    # v2: 同步因子定义到 SQLite (无侵入, 失败不阻断)
    factor_ids = _sync_factor_definitions(cfg, target_groups, windows)

    mode_tag = "增量" if is_incremental else "全量"
    if progress_cb:
        progress_cb(8, f"启动因子流水线，共 {len(target_groups)} 个因子组 ({mode_tag})")
    print(
        f"[2/2] 启动因子流水线, {mode_tag}计算 {len(target_groups)} 个因子组: {target_groups} "
        f"(price_mode={price_mode})"
    )
    n_rows = len(df)
    n_stocks = df["code"].nunique()
    print(f"   数据面板: {n_rows:,} 行 x {n_stocks} 只股票")
    t0 = time.time()

    # ── 断点续传 (仅全量模式) ──
    raw_output = cfg["features"].get(
        "raw_feature_output", "data/features/zz500_alpha158_raw.parquet"
    )
    # checkpoint 属于缓存层, 优先使用 paths.data_cache
    _cache_base = cfg.get("paths", {}).get("data_cache", None)
    if _cache_base:
        ckpt_dir = os.path.join(_cache_base, "alpha158_ckpt")
    else:
        ckpt_dir = os.path.join(os.path.dirname(raw_output) or ".", ".alpha158_ckpt")
    ckpt_meta_path = os.path.join(ckpt_dir, "_meta.json")
    completed_groups: set[str] = set()
    use_checkpoint = not is_incremental

    if use_checkpoint and os.path.exists(ckpt_meta_path):
        try:
            with open(ckpt_meta_path, "r", encoding="utf-8") as f:
                ckpt_meta = json.load(f)
            completed_groups = set(ckpt_meta.get("completed_groups", []))
            # 只恢复本次需要计算的组
            relevant_completed = completed_groups & set(target_groups)
            for gname in list(relevant_completed):
                gfile = os.path.join(ckpt_dir, f"{gname}.parquet")
                if not os.path.exists(gfile):
                    completed_groups.discard(gname)
                    continue
                gdf = pd.read_parquet(gfile)
                feats = [c for c in gdf.columns if c.startswith("feat_")]
                if feats:
                    df = df.merge(gdf[["code", "date"] + feats], on=["code", "date"], how="left")
                all_features.extend(feats)
                group_feature_map[gname] = feats
                del gdf
            if relevant_completed:
                print(f"[CKPT] 断点恢复: 已完成 {len(relevant_completed)}/{len(target_groups)} 组 -- {sorted(relevant_completed)}")
        except Exception as exc:
            logger.warning("断点恢复失败, 全量重算: %s", exc)
            completed_groups = set()

    total_groups = len(target_groups)
    from tqdm import tqdm
    for idx, name in enumerate(tqdm(target_groups, desc="因子计算", unit="组")):
        # 断点续传: 跳过已完成的组
        if name in completed_groups:
            tqdm.write(f"  [SKIP] {name}: 已从断点恢复, 跳过")
            if progress_cb:
                pct = int((idx + 1) / total_groups * 100)
                progress_cb(pct, f"因子计算 [SKIP] {name} (断点恢复)")
            continue

        # v2: 从 registry meta 获取 required cols (消除硬编码)
        required_cols = _get_required_raw_cols(name)
        try:
            validate_raw_schema(df, required_cols)
        except ValueError as exc:
            logger.warning("因子组 %s 所需原始列缺失，跳过: %s", name, exc)
            tqdm.write(f"  [WARN] {name}: 跳过 (缺列: {exc})")
            continue

        # ── 计算因子组 (含计时) ──
        t_group = time.time()
        rss_before = _get_process_rss_mb()

        factor_fn = registry.get_factor(name)
        df, new_feats = factor_fn(df, grouped, windows, f32)

        t_group_elapsed = time.time() - t_group
        rss_after = _get_process_rss_mb()
        rss_delta = rss_after - rss_before if rss_before > 0 and rss_after > 0 else 0

        all_features.extend(new_feats)
        group_feature_map[name] = new_feats

        timing_msg = (
            f"  [OK] {name}: +{len(new_feats)} 个因子, "
            f"耗时 {t_group_elapsed:.1f}s, "
            f"RSS {rss_after:.0f}MB ({rss_delta:+.0f}MB)"
        )
        tqdm.write(timing_msg)
        logger.info(
            "[raw_feature] group=%s cols=%d elapsed=%.1fs rows=%d rss=%.0fMB",
            name, len(new_feats), t_group_elapsed, n_rows, rss_after,
        )

        # ── checkpoint (仅全量模式) ──
        if use_checkpoint:
            try:
                os.makedirs(ckpt_dir, exist_ok=True)
                df[["code", "date"] + new_feats].to_parquet(
                    os.path.join(ckpt_dir, f"{name}.parquet"), index=False, engine="pyarrow",
                )
                with open(ckpt_meta_path, "w", encoding="utf-8") as f:
                    json.dump({
                        "completed_groups": list(completed_groups | {name}),
                        "group_feature_map": group_feature_map,
                    }, f, ensure_ascii=False)
                completed_groups.add(name)
            except Exception as exc:
                logger.warning("因子组 %s checkpoint 保存失败 (不影响主流程): %s", name, exc)

        if progress_cb:
            pct = int((idx + 1) / total_groups * 100)
            progress_cb(pct, f"因子计算 [OK] {name} ({idx+1}/{total_groups})")

    elapsed = time.time() - t0
    print(f"\n[DONE] 特征裂变完毕! 共生成 {len(all_features)} 个因子。耗时: {elapsed:.1f} 秒")

    # checkpoint 暂时保留到原始特征矩阵成功落盘后再清理
    if use_checkpoint and os.path.isdir(ckpt_dir):
        print("[CKPT] 因子组断点缓存已保存, 待矩阵落盘成功后自动清理")

    # 清理 Inf 和早期空值
    df[all_features] = df[all_features].replace([np.inf, -np.inf], np.nan)
    max_window = max(windows)
    # 用最大窗口的基础因子作为有效行标志（确保滚动窗口充分填充）
    sentinel = f"feat_ROC{max_window}"
    if sentinel in df.columns:
        df = df.dropna(subset=[sentinel]).copy()
    else:
        # 没有 rolling 组时用任意已生成因子作为哨兵
        df = df.dropna(subset=all_features, how="all").copy()

    # 删除内部辅助列 (保留 isST / tradestatus 供回测过滤)
    df = df.drop(columns=[c for c in df.columns if c.startswith("_")], errors="ignore")

    return df, all_features, group_feature_map
