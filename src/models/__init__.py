"""
模型自动发现 -- import 此包时注册所有内置模型
扩展方式: 新建 .py 文件, 用 @registry.register_model("name") 装饰, 然后在此导入
"""
from src.models import builtin_models  # noqa: F401
