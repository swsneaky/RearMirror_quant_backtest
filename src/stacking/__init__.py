"""
Stacking 集成学习模块

功能:
  - 多基学习器训练与预测输出对齐
  - 元学习器训练 (加权平均 / 线性回归)
  - 产物持久化

用法:
  from src.stacking import StackingTrainer, StackingPredictor
"""
from src.stacking.stacking_trainer import StackingTrainer
from src.stacking.predictor import StackingPredictor

__all__ = ["StackingTrainer", "StackingPredictor"]
