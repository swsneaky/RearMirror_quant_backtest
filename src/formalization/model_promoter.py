"""
模型晋升器 (ModelPromoter)

职责:
  - 定义晋升准入条件
  - 执行晋升检查
  - 管理晋升流程

准入条件 (默认):
  1. 模型状态为 validated
  2. Sharpe Ratio >= 1.0
  3. ICIR >= 0.5
  4. Max Drawdown <= 30%
  5. 无数据泄露风险

晋升流程:
  1. 检查准入条件
  2. 执行数据泄露检查
  3. 更新模型状态为 promoted
  4. 记录晋升历史
  5. 废弃同类型的旧模型 (可选)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

from src.formalization.model_registry import ModelRegistry, ModelMetadata, ModelStatus

logger = logging.getLogger(__name__)


class PromotionCheckResult(str, Enum):
    """晋升检查结果"""
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"
    SKIP = "skip"


@dataclass
class CheckResult:
    """单个检查的结果"""
    name: str
    result: str                          # pass, fail, warning, skip
    message: str = ""
    value: Any = None
    threshold: Any = None


@dataclass
class PromotionResult:
    """晋升结果"""
    success: bool
    model_id: str
    checks: list[CheckResult] = field(default_factory=list)
    message: str = ""
    promoted_at: str = ""
    deprecated_models: list[str] = field(default_factory=list)

    def all_passed(self) -> bool:
        """是否所有检查都通过"""
        return all(c.result != PromotionCheckResult.FAIL.value for c in self.checks)

    def has_warnings(self) -> bool:
        """是否有警告"""
        return any(c.result == PromotionCheckResult.WARNING.value for c in self.checks)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典"""
        return {
            "success": self.success,
            "model_id": self.model_id,
            "checks": [
                {
                    "name": c.name,
                    "result": c.result,
                    "message": c.message,
                    "value": c.value,
                    "threshold": c.threshold,
                }
                for c in self.checks
            ],
            "message": self.message,
            "promoted_at": self.promoted_at,
            "deprecated_models": self.deprecated_models,
        }


# ================================================================
# 默认准入条件
# ================================================================
DEFAULT_PROMOTION_CRITERIA = {
    "sharpe_ratio": {
        "threshold": 1.0,
        "operator": ">=",
        "description": "Sharpe Ratio >= 1.0",
    },
    "icir": {
        "threshold": 0.5,
        "operator": ">=",
        "description": "ICIR >= 0.5",
    },
    "max_drawdown": {
        "threshold": 0.30,
        "operator": "<=",
        "description": "Max Drawdown <= 30%",
    },
    "information_ratio": {
        "threshold": 0.5,
        "operator": ">=",
        "description": "Information Ratio >= 0.5",
        "optional": True,  # 可选检查
    },
    "avg_turnover": {
        "threshold": 2.0,
        "operator": "<=",
        "description": "Avg Turnover <= 200%",
        "optional": True,
    },
}


class ModelPromoter:
    """
    模型晋升器

    管理模型晋升流程：
      1. 定义准入条件
      2. 执行检查
      3. 晋升模型

    用法:
        promoter = ModelPromoter.from_config(cfg)
        result = promoter.check_and_promote(model_id)
        if result.success:
            print(f"模型晋升成功: {result.model_id}")
    """

    def __init__(
        self,
        registry: ModelRegistry | None = None,
        criteria: dict[str, Any] | None = None,
        cfg: dict | None = None,
        auto_deprecate_old: bool = True,
    ):
        """
        初始化模型晋升器

        Args:
            registry: 模型注册表实例
            criteria: 晋升条件配置
            cfg: 配置字典
            auto_deprecate_old: 是否自动废弃同类型的旧模型
        """
        self.registry = registry or ModelRegistry.from_config(cfg)
        self.criteria = criteria or DEFAULT_PROMOTION_CRITERIA.copy()
        self.cfg = cfg or {}
        self.auto_deprecate_old = auto_deprecate_old
        self._custom_checks: list[Callable[[ModelMetadata], CheckResult]] = []

    @classmethod
    def from_config(cls, cfg: dict | None = None) -> "ModelPromoter":
        """从配置创建"""
        if cfg is None:
            from src.config_loader import load_config
            cfg = load_config()

        registry = ModelRegistry.from_config(cfg)

        # 从配置加载晋升条件
        formalization_cfg = cfg.get("formalization", {})
        criteria = formalization_cfg.get("promotion_criteria", DEFAULT_PROMOTION_CRITERIA)
        auto_deprecate = formalization_cfg.get("auto_deprecate_old", True)

        return cls(
            registry=registry,
            criteria=criteria,
            cfg=cfg,
            auto_deprecate_old=auto_deprecate,
        )

    # --------------------------------------------------
    # 晋升条件检查
    # --------------------------------------------------
    def add_custom_check(
        self,
        check_fn: Callable[[ModelMetadata], CheckResult],
    ) -> None:
        """
        添加自定义检查函数

        Args:
            check_fn: 检查函数，接收 ModelMetadata，返回 CheckResult
        """
        self._custom_checks.append(check_fn)

    def check_criteria(self, metadata: ModelMetadata) -> list[CheckResult]:
        """
        检查晋升条件

        Args:
            metadata: 模型元数据

        Returns:
            检查结果列表
        """
        results = []

        for metric_name, criterion in self.criteria.items():
            threshold = criterion["threshold"]
            operator = criterion["operator"]
            optional = criterion.get("optional", False)
            description = criterion.get("description", f"{metric_name} {operator} {threshold}")

            # 获取指标值
            value = metadata.metrics.get(metric_name)

            if value is None:
                if optional:
                    results.append(CheckResult(
                        name=metric_name,
                        result=PromotionCheckResult.SKIP.value,
                        message=f"可选指标未提供，跳过检查",
                        value=None,
                        threshold=threshold,
                    ))
                else:
                    results.append(CheckResult(
                        name=metric_name,
                        result=PromotionCheckResult.FAIL.value,
                        message=f"必需指标未提供",
                        value=None,
                        threshold=threshold,
                    ))
                continue

            # 执行比较
            passed = self._compare(value, operator, threshold)

            if passed:
                results.append(CheckResult(
                    name=metric_name,
                    result=PromotionCheckResult.PASS.value,
                    message=description,
                    value=value,
                    threshold=threshold,
                ))
            else:
                results.append(CheckResult(
                    name=metric_name,
                    result=PromotionCheckResult.FAIL.value,
                    message=f"{description} (实际值: {value:.4f})",
                    value=value,
                    threshold=threshold,
                ))

        return results

    def _compare(self, value: float, operator: str, threshold: float) -> bool:
        """执行比较操作"""
        if operator == ">=":
            return value >= threshold
        elif operator == ">":
            return value > threshold
        elif operator == "<=":
            return value <= threshold
        elif operator == "<":
            return value < threshold
        elif operator == "==":
            return abs(value - threshold) < 1e-9
        else:
            raise ValueError(f"不支持的操作符: {operator}")

    def check_status(self, metadata: ModelMetadata) -> CheckResult:
        """检查模型状态"""
        if metadata.status == ModelStatus.VALIDATED.value:
            return CheckResult(
                name="status",
                result=PromotionCheckResult.PASS.value,
                message="模型状态为 validated",
                value=metadata.status,
            )
        elif metadata.status == ModelStatus.PROMOTED.value:
            return CheckResult(
                name="status",
                result=PromotionCheckResult.FAIL.value,
                message="模型已晋升，无需重复操作",
                value=metadata.status,
            )
        else:
            return CheckResult(
                name="status",
                result=PromotionCheckResult.FAIL.value,
                message=f"模型状态为 {metadata.status}，需要先验证",
                value=metadata.status,
            )

    def check_data_leakage(self, metadata: ModelMetadata) -> CheckResult:
        """
        检查数据泄露风险

        这是简化的检查，实际项目需要更复杂的逻辑：
          - 检查训练/测试时间范围
          - 检查特征是否包含未来信息
          - 检查标签生成逻辑
        """
        # 检查配置中的隔离带
        training_config = metadata.training_config or {}
        gap = training_config.get("gap", 0)

        if gap >= 5:  # 默认要求 gap >= 5 天
            return CheckResult(
                name="data_leakage",
                result=PromotionCheckResult.PASS.value,
                message=f"隔离带设置合理: gap={gap}",
                value=gap,
                threshold=5,
            )
        else:
            return CheckResult(
                name="data_leakage",
                result=PromotionCheckResult.WARNING.value,
                message=f"隔离带可能不足: gap={gap}，建议 >= 5",
                value=gap,
                threshold=5,
            )

    def run_all_checks(self, metadata: ModelMetadata) -> list[CheckResult]:
        """
        运行所有检查

        Args:
            metadata: 模型元数据

        Returns:
            检查结果列表
        """
        results = []

        # 1. 状态检查
        results.append(self.check_status(metadata))

        # 2. 指标条件检查
        results.extend(self.check_criteria(metadata))

        # 3. 数据泄露检查
        results.append(self.check_data_leakage(metadata))

        # 4. 自定义检查
        for check_fn in self._custom_checks:
            try:
                results.append(check_fn(metadata))
            except Exception as exc:
                results.append(CheckResult(
                    name="custom_check",
                    result=PromotionCheckResult.FAIL.value,
                    message=f"自定义检查异常: {exc}",
                ))

        return results

    # --------------------------------------------------
    # 晋升操作
    # --------------------------------------------------
    def promote(
        self,
        model_id: str,
        force: bool = False,
    ) -> PromotionResult:
        """
        晋升模型

        Args:
            model_id: 模型 ID
            force: 是否强制晋升（忽略部分检查失败）

        Returns:
            PromotionResult 晋升结果
        """
        # 获取模型元数据
        metadata = self.registry.get(model_id)
        if metadata is None:
            return PromotionResult(
                success=False,
                model_id=model_id,
                message=f"模型不存在: {model_id}",
            )

        # 运行检查
        checks = self.run_all_checks(metadata)

        # 判断是否可以晋升
        has_fail = any(c.result == PromotionCheckResult.FAIL.value for c in checks)
        can_promote = not has_fail or force

        if not can_promote:
            return PromotionResult(
                success=False,
                model_id=model_id,
                checks=checks,
                message="晋升条件未满足",
            )

        # 执行晋升
        deprecated_models = []

        # 更新模型状态
        self.registry.update_status(
            model_id,
            ModelStatus.PROMOTED.value,
            message="模型晋升成功",
        )

        # 记录晋升历史
        metadata = self.registry.get(model_id)  # 重新获取更新后的元数据
        if metadata:
            metadata.promotion_history.append({
                "timestamp": datetime.now().isoformat(),
                "action": "promoted",
                "checks": [c.to_dict() if hasattr(c, 'to_dict') else c for c in checks],
                "force": force,
            })
            if metadata.metadata_path:
                metadata.to_json(metadata.metadata_path)

        # 废弃同类型的旧模型
        if self.auto_deprecate_old and metadata:
            old_models = self.registry.list(
                status=ModelStatus.PROMOTED.value,
            )
            # 手动过滤同类型
            for old_model in old_models:
                if old_model.model_id != model_id and old_model.model_type == metadata.model_type:
                    self.registry.deprecate(
                        old_model.model_id,
                        reason=f"被新模型 {model_id} 替代",
                    )
                    deprecated_models.append(old_model.model_id)

        return PromotionResult(
            success=True,
            model_id=model_id,
            checks=checks,
            message="模型晋升成功",
            promoted_at=datetime.now().isoformat(),
            deprecated_models=deprecated_models,
        )

    def check_and_promote(self, model_id: str) -> PromotionResult:
        """
        检查并晋升模型（便捷方法）

        Args:
            model_id: 模型 ID

        Returns:
            PromotionResult 晋升结果
        """
        return self.promote(model_id, force=False)

    # --------------------------------------------------
    # 报告生成
    # --------------------------------------------------
    def generate_promotion_report(
        self,
        result: PromotionResult,
        output_path: str | None = None,
    ) -> str:
        """
        生成晋升报告

        Args:
            result: 晋升结果
            output_path: 输出路径（可选）

        Returns:
            报告内容（JSON 字符串）
        """
        report = {
            "promotion_result": result.to_dict(),
            "generated_at": datetime.now().isoformat(),
            "criteria_used": self.criteria,
        }

        report_json = json.dumps(report, indent=2, ensure_ascii=False, default=str)

        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(report_json)
            logger.info(f"晋升报告已保存: {output_path}")

        return report_json


def run_promotion_pipeline(
    model_id: str,
    cfg: dict | None = None,
    auto_validate: bool = True,
) -> PromotionResult:
    """
    模型晋升流水线

    便捷函数：执行完整的晋升流程

    Args:
        model_id: 模型 ID
        cfg: 配置字典
        auto_validate: 是否自动标记为 validated

    Returns:
        PromotionResult 晋升结果
    """
    if cfg is None:
        from src.config_loader import load_config
        cfg = load_config()

    registry = ModelRegistry.from_config(cfg)
    promoter = ModelPromoter.from_config(cfg)

    # 检查模型是否存在
    metadata = registry.get(model_id)
    if metadata is None:
        return PromotionResult(
            success=False,
            model_id=model_id,
            message=f"模型不存在: {model_id}",
        )

    # 自动验证
    if auto_validate and metadata.status == ModelStatus.REGISTERED.value:
        registry.validate(model_id)
        logger.info(f"模型已自动验证: {model_id}")

    # 执行晋升
    return promoter.check_and_promote(model_id)
