"""
模型注册表 (ModelRegistry)

职责:
  - 模型版本管理
  - 模型元数据存储
  - 模型生命周期管理 (registered -> validated -> promoted -> deprecated)

产物格式:
  model_metadata.json:
    {
      "model_id": "xgb_20260414_001",
      "model_type": "xgboost",
      "version": "1.0.0",
      "status": "registered",
      "created_at": "2026-04-14T10:00:00",
      "updated_at": "2026-04-14T10:00:00",
      "metrics": {
        "sharpe_ratio": 1.5,
        "ic_mean": 0.05,
        "icir": 1.2,
        ...
      },
      "training_config": {...},
      "feature_set_id": "fs_abc123",
      "label_set_id": "ls_xyz789",
      "model_path": "models/xgb_20260414_001.pkl",
      "metadata_path": "models/xgb_20260414_001_metadata.json",
      "promotion_history": []
    }

存储:
  - SQLite: model_registry 表
  - 文件系统: models/{model_id}/
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class ModelStatus(str, Enum):
    """模型状态"""
    REGISTERED = "registered"      # 已注册，待验证
    VALIDATED = "validated"        # 已验证，可晋升
    PROMOTED = "promoted"          # 已晋升，正式使用
    DEPRECATED = "deprecated"      # 已废弃
    FAILED = "failed"              # 验证失败


@dataclass
class ModelMetadata:
    """模型元数据"""
    model_id: str
    model_type: str                          # xgboost, lightgbm, stacking, etc.
    version: str = "1.0.0"
    status: str = ModelStatus.REGISTERED.value
    created_at: str = ""
    updated_at: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    training_config: dict[str, Any] = field(default_factory=dict)
    feature_set_id: Optional[str] = None
    label_set_id: Optional[str] = None
    model_path: str = ""
    metadata_path: str = ""
    promotion_history: list[dict[str, Any]] = field(default_factory=list)
    description: str = ""
    tags: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelMetadata":
        """从字典创建"""
        return cls(**data)

    def to_json(self, path: str) -> None:
        """保存为 JSON 文件"""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False, default=str)

    @classmethod
    def from_json(cls, path: str) -> "ModelMetadata":
        """从 JSON 文件加载"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)


class ModelRegistry:
    """
    模型注册表

    管理模型的生命周期：
      1. register() -- 注册新模型
      2. validate() -- 验证模型
      3. promote()  -- 晋升模型 (通过 ModelPromoter)
      4. deprecate() -- 废弃模型

    用法:
        registry = ModelRegistry.from_config(cfg)
        model_id = registry.register(
            model_type="xgboost",
            model_path="data/results/xgb_model.pkl",
            metrics={"sharpe_ratio": 1.5, ...},
            feature_set_id="fs_abc123",
            label_set_id="ls_xyz789",
        )
    """

    def __init__(
        self,
        registry_dir: str = "models",
        cfg: dict | None = None,
    ):
        """
        初始化模型注册表

        Args:
            registry_dir: 模型注册目录
            cfg: 配置字典
        """
        self.registry_dir = Path(registry_dir)
        self.cfg = cfg or {}
        self.registry_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_config(cls, cfg: dict | None = None) -> "ModelRegistry":
        """从配置创建"""
        if cfg is None:
            from src.config_loader import load_config
            cfg = load_config()

        registry_dir = cfg.get("paths", {}).get("models", "models")
        return cls(registry_dir=registry_dir, cfg=cfg)

    # --------------------------------------------------
    # 注册接口
    # --------------------------------------------------
    def register(
        self,
        model_type: str,
        model_path: str,
        metrics: dict[str, Any],
        feature_set_id: str | None = None,
        label_set_id: str | None = None,
        training_config: dict[str, Any] | None = None,
        version: str = "1.0.0",
        description: str = "",
        tags: list[str] | None = None,
        copy_model: bool = True,
    ) -> str:
        """
        注册新模型

        Args:
            model_type: 模型类型 (xgboost, lightgbm, stacking, etc.)
            model_path: 模型文件路径
            metrics: 模型评估指标
            feature_set_id: 关联的特征集 ID
            label_set_id: 关联的标签集 ID
            training_config: 训练配置
            version: 模型版本
            description: 模型描述
            tags: 标签列表
            copy_model: 是否复制模型文件到注册目录

        Returns:
            model_id: 模型唯一标识
        """
        # 生成模型 ID
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        model_id = f"{model_type}_{timestamp}"

        # 创建模型目录
        model_dir = self.registry_dir / model_id
        model_dir.mkdir(parents=True, exist_ok=True)

        # 复制模型文件
        final_model_path = model_path
        if copy_model and os.path.exists(model_path):
            import shutil
            ext = Path(model_path).suffix
            dest_path = model_dir / f"model{ext}"
            shutil.copy2(model_path, dest_path)
            final_model_path = str(dest_path)
            logger.info(f"[ModelRegistry] 模型文件已复制: {model_path} -> {dest_path}")

        # 创建元数据
        metadata = ModelMetadata(
            model_id=model_id,
            model_type=model_type,
            version=version,
            status=ModelStatus.REGISTERED.value,
            metrics=metrics,
            training_config=training_config or {},
            feature_set_id=feature_set_id,
            label_set_id=label_set_id,
            model_path=final_model_path,
            description=description,
            tags=tags or [],
        )

        # 保存元数据
        metadata_path = model_dir / "model_metadata.json"
        metadata.metadata_path = str(metadata_path)
        metadata.to_json(str(metadata_path))

        # 注册到数据库
        self._register_to_db(metadata)

        logger.info(f"[ModelRegistry] 模型已注册: {model_id}")
        return model_id

    def _register_to_db(self, metadata: ModelMetadata) -> None:
        """将模型注册到数据库"""
        con = self._get_db_connection()
        if con is None:
            logger.warning("数据库连接不可用，跳过注册")
            return

        try:
            # 检查表是否存在
            con.execute("""
                CREATE TABLE IF NOT EXISTS model_registry (
                    model_id       TEXT PRIMARY KEY,
                    model_type     TEXT NOT NULL,
                    version        TEXT NOT NULL,
                    status         TEXT NOT NULL,
                    created_at     TEXT NOT NULL,
                    updated_at     TEXT NOT NULL,
                    metrics_json   TEXT,
                    training_config_json TEXT,
                    feature_set_id TEXT,
                    label_set_id   TEXT,
                    model_path     TEXT,
                    metadata_path  TEXT,
                    description    TEXT,
                    tags_json      TEXT,
                    promotion_history_json TEXT
                )
            """)

            con.execute("""
                INSERT OR REPLACE INTO model_registry
                    (model_id, model_type, version, status, created_at, updated_at,
                     metrics_json, training_config_json, feature_set_id, label_set_id,
                     model_path, metadata_path, description, tags_json, promotion_history_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                metadata.model_id,
                metadata.model_type,
                metadata.version,
                metadata.status,
                metadata.created_at,
                metadata.updated_at,
                json.dumps(metadata.metrics, default=str),
                json.dumps(metadata.training_config, default=str),
                metadata.feature_set_id,
                metadata.label_set_id,
                metadata.model_path,
                metadata.metadata_path,
                metadata.description,
                json.dumps(metadata.tags),
                json.dumps(metadata.promotion_history, default=str),
            ])
            logger.debug(f"[ModelRegistry] 数据库注册完成: {metadata.model_id}")
        except Exception as exc:
            logger.error(f"[ModelRegistry] 数据库注册失败: {exc}")

    def _get_db_connection(self):
        """获取数据库连接"""
        if not self.cfg:
            return None
        try:
            from src.data_layer.db import get_connection
            return get_connection(self.cfg)
        except Exception as exc:
            logger.warning(f"数据库连接失败: {exc}")
            return None

    # --------------------------------------------------
    # 查询接口
    # --------------------------------------------------
    def get(self, model_id: str) -> ModelMetadata | None:
        """获取模型元数据"""
        # 优先从文件加载
        metadata_path = self.registry_dir / model_id / "model_metadata.json"
        if metadata_path.exists():
            return ModelMetadata.from_json(str(metadata_path))

        # 从数据库加载
        con = self._get_db_connection()
        if con is not None:
            try:
                row = con.execute(
                    "SELECT * FROM model_registry WHERE model_id = ?", [model_id]
                ).fetchone()
                if row:
                    cols = [d[0] for d in con.description]
                    data = dict(zip(cols, row))
                    return ModelMetadata(
                        model_id=data["model_id"],
                        model_type=data["model_type"],
                        version=data["version"],
                        status=data["status"],
                        created_at=data["created_at"],
                        updated_at=data["updated_at"],
                        metrics=json.loads(data["metrics_json"] or "{}"),
                        training_config=json.loads(data["training_config_json"] or "{}"),
                        feature_set_id=data["feature_set_id"],
                        label_set_id=data["label_set_id"],
                        model_path=data["model_path"],
                        metadata_path=data["metadata_path"],
                        description=data["description"] or "",
                        tags=json.loads(data["tags_json"] or "[]"),
                        promotion_history=json.loads(data["promotion_history_json"] or "[]"),
                    )
            except Exception as exc:
                logger.warning(f"从数据库加载模型失败: {exc}")

        return None

    def list(
        self,
        status: str | None = None,
        model_type: str | None = None,
        limit: int = 100,
    ) -> list[ModelMetadata]:
        """
        列出模型

        Args:
            status: 按状态过滤
            model_type: 按模型类型过滤
            limit: 返回数量限制

        Returns:
            模型元数据列表
        """
        models = []

        # 从目录扫描
        for model_dir in self.registry_dir.iterdir():
            if not model_dir.is_dir():
                continue

            metadata_path = model_dir / "model_metadata.json"
            if metadata_path.exists():
                try:
                    metadata = ModelMetadata.from_json(str(metadata_path))

                    # 过滤
                    if status and metadata.status != status:
                        continue
                    if model_type and metadata.model_type != model_type:
                        continue

                    models.append(metadata)
                except Exception as exc:
                    logger.warning(f"加载模型元数据失败: {metadata_path}: {exc}")

        # 按创建时间排序
        models.sort(key=lambda m: m.created_at, reverse=True)

        return models[:limit]

    # --------------------------------------------------
    # 状态更新接口
    # --------------------------------------------------
    def update_status(
        self,
        model_id: str,
        status: str,
        message: str = "",
    ) -> bool:
        """
        更新模型状态

        Args:
            model_id: 模型 ID
            status: 新状态
            message: 状态变更消息

        Returns:
            是否成功
        """
        metadata = self.get(model_id)
        if metadata is None:
            logger.error(f"模型不存在: {model_id}")
            return False

        old_status = metadata.status
        metadata.status = status
        metadata.updated_at = datetime.now().isoformat()

        # 记录状态变更
        if message:
            metadata.promotion_history.append({
                "timestamp": metadata.updated_at,
                "action": f"status_change: {old_status} -> {status}",
                "message": message,
            })

        # 保存
        if metadata.metadata_path:
            metadata.to_json(metadata.metadata_path)

        # 更新数据库
        self._register_to_db(metadata)

        logger.info(f"[ModelRegistry] 模型状态更新: {model_id} {old_status} -> {status}")
        return True

    def validate(self, model_id: str) -> bool:
        """
        验证模型 (标记为 validated)

        Args:
            model_id: 模型 ID

        Returns:
            是否成功
        """
        return self.update_status(
            model_id,
            ModelStatus.VALIDATED.value,
            message="模型验证通过",
        )

    def deprecate(self, model_id: str, reason: str = "") -> bool:
        """
        废弃模型

        Args:
            model_id: 模型 ID
            reason: 废弃原因

        Returns:
            是否成功
        """
        return self.update_status(
            model_id,
            ModelStatus.DEPRECATED.value,
            message=f"模型已废弃: {reason}",
        )

    # --------------------------------------------------
    # 获取正式模型
    # --------------------------------------------------
    def get_promoted_models(self) -> list[ModelMetadata]:
        """获取所有已晋升的正式模型"""
        return self.list(status=ModelStatus.PROMOTED.value)

    def get_latest_promoted(self, model_type: str | None = None) -> ModelMetadata | None:
        """
        获取最新晋升的正式模型

        Args:
            model_type: 可选的模型类型过滤

        Returns:
            最新晋升的模型元数据，若无则返回 None
        """
        promoted = self.list(status=ModelStatus.PROMOTED.value)
        if model_type:
            promoted = [m for m in promoted if m.model_type == model_type]

        if not promoted:
            return None

        return promoted[0]  # 已按时间排序

    # --------------------------------------------------
    # 删除接口
    # --------------------------------------------------
    def delete(self, model_id: str) -> bool:
        """
        删除模型

        Args:
            model_id: 模型 ID

        Returns:
            是否成功
        """
        import shutil

        metadata = self.get(model_id)
        if metadata is None:
            logger.error(f"模型不存在: {model_id}")
            return False

        # 删除模型目录
        model_dir = self.registry_dir / model_id
        if model_dir.exists():
            shutil.rmtree(model_dir)

        # 从数据库删除
        con = self._get_db_connection()
        if con is not None:
            try:
                con.execute("DELETE FROM model_registry WHERE model_id = ?", [model_id])
            except Exception as exc:
                logger.warning(f"从数据库删除模型失败: {exc}")

        logger.info(f"[ModelRegistry] 模型已删除: {model_id}")
        return True


def register_model_from_experiment(
    experiment_id: str,
    cfg: dict | None = None,
    description: str = "",
    tags: list[str] | None = None,
) -> str | None:
    """
    从实验结果注册模型

    便捷函数：从已完成的实验中提取模型并注册

    Args:
        experiment_id: 实验 ID
        cfg: 配置字典
        description: 模型描述
        tags: 标签列表

    Returns:
        model_id 或 None
    """
    if cfg is None:
        from src.config_loader import load_config
        cfg = load_config()

    # 查找实验结果目录
    results_dir = Path(cfg.get("paths", {}).get("data_results", "data/results"))
    exp_dir = results_dir / experiment_id

    if not exp_dir.exists():
        logger.error(f"实验目录不存在: {exp_dir}")
        return None

    # 读取指标
    metrics_path = exp_dir / "results" / "metrics_summary.json"
    if not metrics_path.exists():
        logger.error(f"指标文件不存在: {metrics_path}")
        return None

    with open(metrics_path, "r", encoding="utf-8") as f:
        metrics = json.load(f)

    # 查找模型文件
    models_dir = exp_dir / "models"
    model_path = None
    model_type = cfg.get("model", {}).get("active", "unknown")

    if models_dir.exists():
        for ext in [".pkl", ".joblib", ".json"]:
            model_files = list(models_dir.glob(f"*{ext}"))
            if model_files:
                model_path = str(model_files[0])
                break

    if model_path is None:
        logger.warning(f"未找到模型文件，将创建引用注册")

    # 注册
    registry = ModelRegistry.from_config(cfg)
    model_id = registry.register(
        model_type=model_type,
        model_path=model_path or "",
        metrics=metrics,
        training_config=cfg.get("model", {}),
        description=description or f"From experiment {experiment_id}",
        tags=tags or [experiment_id],
        copy_model=bool(model_path),
    )

    return model_id
