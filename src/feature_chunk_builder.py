"""
分块特征重建模块 -- 实现分段计算、分段落盘、原子发布机制

设计目标:
1. 避免一次性全量加载导致内存溢出
2. 支持断点续跑
3. 原子发布到正式表

使用方式:
    from src.feature_chunk_builder import run_feature_chunk_rebuild
    result = run_feature_chunk_rebuild(cfg, resume=True)
"""
from __future__ import annotations

import gc
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# 默认参数
DEFAULT_CHUNK_DAYS = 256  # 每个chunk约1年交易日
DEFAULT_WARMUP_DAYS = 70  # max_window(60) + buffer(10)


@dataclass
class ChunkInfo:
    """单个chunk的元数据"""
    chunk_id: int
    warmup_start: str  # 预热期起始日期
    chunk_start: str   # 实际数据起始日期
    chunk_end: str     # 实际数据结束日期
    status: str = "pending"  # pending | completed | failed
    rows: int = 0
    cols: list[str] = field(default_factory=list)
    file_path: str = ""
    error: str = ""


class ChunkManifest:
    """
    管理chunk元数据和完成状态。
    持久化到 _manifest.json 文件。
    """

    def __init__(self, manifest_path: str):
        self.manifest_path = Path(manifest_path)
        self.chunks: dict[int, ChunkInfo] = {}
        self.created_at: str = ""
        self.updated_at: str = ""
        self._load()

    def _load(self) -> None:
        """从文件加载manifest"""
        if self.manifest_path.exists():
            try:
                with open(self.manifest_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.created_at = data.get("created_at", "")
                self.updated_at = data.get("updated_at", "")
                for cid, cdata in data.get("chunks", {}).items():
                    self.chunks[int(cid)] = ChunkInfo(**cdata)
                logger.info("Loaded manifest with %d chunks", len(self.chunks))
            except Exception as exc:
                logger.warning("Failed to load manifest: %s", exc)
                self.chunks = {}

    def _save(self) -> None:
        """保存manifest到文件"""
        now = datetime.now().isoformat(timespec="seconds")
        if not self.created_at:
            self.created_at = now
        self.updated_at = now

        data = {
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "chunks": {
                str(cid): {
                    "chunk_id": c.chunk_id,
                    "warmup_start": c.warmup_start,
                    "chunk_start": c.chunk_start,
                    "chunk_end": c.chunk_end,
                    "status": c.status,
                    "rows": c.rows,
                    "cols": c.cols,
                    "file_path": c.file_path,
                    "error": c.error,
                }
                for cid, c in self.chunks.items()
            },
        }

        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.debug("Saved manifest to %s", self.manifest_path)

    def add_chunk(self, info: ChunkInfo) -> None:
        """添加chunk元数据"""
        self.chunks[info.chunk_id] = info
        self._save()

    def mark_completed(self, chunk_id: int, rows: int, cols: list[str], file_path: str) -> None:
        """标记chunk为已完成"""
        if chunk_id in self.chunks:
            c = self.chunks[chunk_id]
            c.status = "completed"
            c.rows = rows
            c.cols = cols
            c.file_path = file_path
            self._save()

    def mark_failed(self, chunk_id: int, error: str) -> None:
        """标记chunk为失败"""
        if chunk_id in self.chunks:
            c = self.chunks[chunk_id]
            c.status = "failed"
            c.error = error
            self._save()

    def is_completed(self, chunk_id: int) -> bool:
        """检查chunk是否已完成"""
        c = self.chunks.get(chunk_id)
        return c is not None and c.status == "completed"

    def get_resume_from(self) -> int:
        """返回下一个未完成的chunk索引"""
        for cid in sorted(self.chunks.keys()):
            if self.chunks[cid].status != "completed":
                return cid
        return len(self.chunks)  # 全部完成

    def all_completed(self) -> bool:
        """检查所有chunk是否完成"""
        return all(c.status == "completed" for c in self.chunks.values())

    def get_total_rows(self) -> int:
        """获取已完成chunk的总行数"""
        return sum(c.rows for c in self.chunks.values() if c.status == "completed")


def compute_date_chunks(
    dates: list[str],
    chunk_days: int = DEFAULT_CHUNK_DAYS,
    warmup_days: int = DEFAULT_WARMUP_DAYS,
) -> list[dict]:
    """
    将日期列表划分为带warmup的chunk。

    每个chunk包含:
      - warmup_start: 预热期起始（用于滚动窗口计算）
      - chunk_start: 实际数据起始
      - chunk_end: 实际数据结束

    Args:
        dates: 排序后的日期列表 (YYYY-MM-DD)
        chunk_days: 每个chunk的实际数据天数
        warmup_days: 预热期天数

    Returns:
        list of dict with chunk metadata
    """
    if not dates:
        return []

    chunks = []
    n = len(dates)

    chunk_id = 0
    i = 0
    while i < n:
        # 计算warmup起始位置
        warmup_start_idx = max(0, i - warmup_days)
        # 计算chunk结束位置
        chunk_end_idx = min(i + chunk_days, n)

        chunk_info = {
            "chunk_id": chunk_id,
            "warmup_start": dates[warmup_start_idx],
            "chunk_start": dates[i],
            "chunk_end": dates[chunk_end_idx - 1],  # 闭区间
            "warmup_start_idx": warmup_start_idx,
            "chunk_start_idx": i,
            "chunk_end_idx": chunk_end_idx,
        }
        chunks.append(chunk_info)

        chunk_id += 1
        i = chunk_end_idx

        # 最后一个chunk如果剩余天数太少，合并到上一个
        # (这里简化处理，保持独立chunk)

    logger.info("Computed %d chunks from %d dates (chunk_days=%d, warmup=%d)",
                len(chunks), n, chunk_days, warmup_days)
    return chunks


class FeatureChunkBuilder:
    """
    分块特征计算器。

    工作流程:
    1. 从 daily_bar 加载日期列表
    2. 计算日期chunk划分
    3. 逐chunk计算原始特征
    4. 保存到parquet分片
    5. 原子发布到 feature_wide 表
    """

    def __init__(
        self,
        cfg: dict,
        chunk_days: int = DEFAULT_CHUNK_DAYS,
        warmup_days: int = DEFAULT_WARMUP_DAYS,
    ):
        self.cfg = cfg
        self.chunk_days = chunk_days
        self.warmup_days = warmup_days

        # 路径配置
        paths = cfg.get("paths", {})
        cache_base = paths.get("data_cache", "data/cache")
        self.temp_dir = Path(cache_base) / "feature_chunks_temp"
        self.final_dir = Path(cache_base) / "feature_chunks"
        self.manifest_path = self.final_dir / "_manifest.json"

        # 确保目录存在
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.final_dir.mkdir(parents=True, exist_ok=True)

    def build_all_chunks(self, resume: bool = True) -> dict:
        """
        执行全部分块计算，支持断点续跑。

        Args:
            resume: 是否从上次中断处继续

        Returns:
            dict with stats and status
        """
        # 1. 获取所有交易日
        dates = self._get_all_trade_dates()
        if not dates:
            return {"status": "error", "error": "No trade dates found"}

        # 2. 计算chunk划分
        chunk_list = compute_date_chunks(dates, self.chunk_days, self.warmup_days)

        # 3. 初始化/加载manifest
        manifest = ChunkManifest(str(self.manifest_path))

        # 如果不续跑，清空旧数据
        if not resume:
            manifest = ChunkManifest(str(self.manifest_path))
            for f in self.temp_dir.glob("chunk_*.parquet"):
                f.unlink()
            for f in self.final_dir.glob("chunk_*.parquet"):
                f.unlink()

        # 注册chunk到manifest
        for c in chunk_list:
            if c["chunk_id"] not in manifest.chunks:
                manifest.add_chunk(ChunkInfo(
                    chunk_id=c["chunk_id"],
                    warmup_start=c["warmup_start"],
                    chunk_start=c["chunk_start"],
                    chunk_end=c["chunk_end"],
                ))

        # 4. 确定起始chunk
        start_chunk = manifest.get_resume_from() if resume else 0
        if start_chunk >= len(chunk_list):
            logger.info("All chunks already completed")
            return {
                "status": "completed",
                "total_chunks": len(chunk_list),
                "total_rows": manifest.get_total_rows(),
            }

        logger.info("Starting from chunk %d / %d", start_chunk, len(chunk_list))

        # 5. 逐chunk计算
        for i in range(start_chunk, len(chunk_list)):
            c = chunk_list[i]
            chunk_id = c["chunk_id"]

            if manifest.is_completed(chunk_id):
                logger.info("Chunk %d already completed, skipping", chunk_id)
                continue

            logger.info("Processing chunk %d/%d: %s to %s",
                       chunk_id + 1, len(chunk_list), c["chunk_start"], c["chunk_end"])

            try:
                df = self._build_single_chunk(c)
                file_path = self._save_chunk(chunk_id, df)

                # 获取特征列
                feat_cols = [col for col in df.columns if col.startswith("feat_")]

                manifest.mark_completed(chunk_id, len(df), feat_cols, str(file_path))

                # 内存清理
                del df
                gc.collect()

            except Exception as exc:
                logger.error("Chunk %d failed: %s", chunk_id, exc)
                manifest.mark_failed(chunk_id, str(exc))
                return {
                    "status": "error",
                    "failed_chunk": chunk_id,
                    "error": str(exc),
                }

        # 6. 返回结果
        return {
            "status": "completed",
            "total_chunks": len(chunk_list),
            "total_rows": manifest.get_total_rows(),
            "manifest_path": str(self.manifest_path),
        }

    def _get_all_trade_dates(self) -> list[str]:
        """从daily_bar获取所有唯一交易日"""
        from src.data_layer.db import get_connection

        con = get_connection(self.cfg)
        df = pd.read_sql_query(
            "SELECT DISTINCT date FROM daily_bar ORDER BY date",
            con
        )
        return df["date"].tolist()

    def _build_single_chunk(self, chunk_info: dict) -> pd.DataFrame:
        """
        计算单个chunk的原始特征。

        加载warmup期数据用于滚动窗口计算，
        但只保留chunk_start到chunk_end的数据。
        """
        from src.data_layer.db import get_connection
        from src.price_mode import apply_price_mode, get_price_mode
        from src.feature_engine import build_alpha158

        warmup_start = chunk_info["warmup_start"]
        chunk_start = chunk_info["chunk_start"]
        chunk_end = chunk_info["chunk_end"]

        # 加载数据 (含warmup)
        con = get_connection(self.cfg)
        query = f"""
            SELECT * FROM daily_bar
            WHERE date >= '{warmup_start}' AND date <= '{chunk_end}'
            ORDER BY code, date
        """
        df = pd.read_sql_query(query, con)

        if df.empty:
            raise ValueError(f"No data for chunk {chunk_info['chunk_id']}")

        logger.info("Loaded %d rows for chunk %d (warmup=%s, end=%s)",
                   len(df), chunk_info["chunk_id"], warmup_start, chunk_end)

        # 应用价格模式 (前复权)
        price_mode = get_price_mode(self.cfg)
        df = apply_price_mode(df, price_mode)

        # 计算原始特征 (传入切片数据)
        df_result, all_features, group_map = build_alpha158(
            self.cfg,
            factor_groups=self.cfg["features"].get("active_factors"),
            input_df=df,
        )

        # 只保留chunk范围内的数据
        df_result = df_result[
            (df_result["date"] >= chunk_start) &
            (df_result["date"] <= chunk_end)
        ].copy()

        logger.info("Built chunk %d: %d rows, %d features",
                   chunk_info["chunk_id"], len(df_result), len(all_features))

        return df_result

    def _save_chunk(self, chunk_id: int, df: pd.DataFrame) -> Path:
        """保存chunk到parquet"""
        file_path = self.temp_dir / f"chunk_{chunk_id:04d}.parquet"
        df.to_parquet(file_path, index=False, engine="pyarrow")
        logger.info("Saved chunk %d to %s (%d rows)", chunk_id, file_path, len(df))
        return file_path

    def publish_to_feature_wide(self) -> dict:
        """
        原子发布：验证所有chunk后合并写入feature_wide。

        步骤:
        1. 验证所有chunk完整性
        2. 验证文件存在
        3. 逐chunk写入feature_wide表
        4. 移动temp目录到final目录
        """
        manifest = ChunkManifest(str(self.manifest_path))

        # 1. 验证完整性
        if not manifest.all_completed():
            incomplete = [cid for cid, c in manifest.chunks.items()
                         if c.status != "completed"]
            return {
                "status": "error",
                "error": f"Incomplete chunks: {incomplete}",
            }

        # 2. 验证文件存在
        for cid, c in manifest.chunks.items():
            if c.file_path:
                if not Path(c.file_path).exists():
                    return {
                        "status": "error",
                        "error": f"Missing file for chunk {cid}: {c.file_path}",
                    }

        # 3. 逐chunk写入feature_wide表（避免OOM）
        logger.info("Writing %d chunks to feature_wide...", len(manifest.chunks))

        from src.data_layer.db import get_connection, table_exists

        con = get_connection(self.cfg)
        total_rows = 0
        total_cols = 0
        first_chunk = True

        for cid in sorted(manifest.chunks.keys()):
            c = manifest.chunks[cid]
            if c.file_path:
                df = pd.read_parquet(c.file_path)
                if first_chunk:
                    # 清空旧数据
                    if table_exists(self.cfg, "feature_wide"):
                        con.execute("DELETE FROM feature_wide")
                        logger.info("Cleared existing feature_wide table")
                    con.df_to_table("feature_wide", df, if_exists="replace")
                    first_chunk = False
                else:
                    con.df_to_table("feature_wide", df, if_exists="append")
                total_rows += len(df)
                total_cols = max(total_cols, len(df.columns))
                logger.info("Wrote chunk %d to feature_wide (%d rows)", cid, len(df))

        if total_rows == 0:
            return {"status": "error", "error": "No data to merge"}

        # 4. 移动temp到final
        if self.temp_dir.exists():
            # 删除旧的final目录
            if self.final_dir.exists():
                shutil.rmtree(self.final_dir)
            # 重命名
            shutil.move(str(self.temp_dir), str(self.final_dir))
            logger.info("Moved temp to final directory")

        return {
            "status": "success",
            "rows": total_rows,
            "cols": total_cols,
            "chunks": len(manifest.chunks),
        }

    def get_memory_stats(self) -> dict:
        """获取当前内存使用情况"""
        try:
            import psutil
            process = psutil.Process()
            mem = process.memory_info()
            return {
                "rss_mb": mem.rss / (1024 * 1024),
                "vms_mb": mem.vms / (1024 * 1024),
            }
        except ImportError:
            return {"rss_mb": -1, "vms_mb": -1}


def run_feature_chunk_rebuild(
    cfg: dict,
    chunk_days: int = DEFAULT_CHUNK_DAYS,
    warmup_days: int = DEFAULT_WARMUP_DAYS,
    resume: bool = True,
    publish: bool = False,
) -> dict:
    """
    分块重建原始特征矩阵入口函数。

    Args:
        cfg: 配置字典
        chunk_days: 每个chunk的天数
        warmup_days: 预热期天数
        resume: 是否断点续跑
        publish: 是否立即发布到feature_wide

    Returns:
        dict with build stats and status
    """
    builder = FeatureChunkBuilder(cfg, chunk_days, warmup_days)

    # 执行分块计算
    result = builder.build_all_chunks(resume=resume)

    if result["status"] != "completed":
        return result

    # 可选：立即发布
    if publish:
        publish_result = builder.publish_to_feature_wide()
        result["publish"] = publish_result

    return result


def publish_feature_chunks(cfg: dict) -> dict:
    """
    发布已完成的chunk到feature_wide表。

    用于在build_all_chunks完成后单独执行发布。
    """
    builder = FeatureChunkBuilder(cfg)
    return builder.publish_to_feature_wide()
