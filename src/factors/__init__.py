"""
因子自动发现 -- import 此包时自动注册所有内置因子
扩展方式: 新建 .py 文件, 用 @registry.register_factor("name") 装饰, 然后在此导入
"""
from src.factors import builtin_kline        # noqa: F401
from src.factors import builtin_rolling      # noqa: F401
from src.factors import builtin_rolling_ext  # noqa: F401
from src.factors import builtin_technical    # noqa: F401
from src.factors import builtin_turnover     # noqa: F401
from src.factors import builtin_valuation    # noqa: F401
