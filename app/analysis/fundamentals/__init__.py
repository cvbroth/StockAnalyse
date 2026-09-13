"""可替换的基本面分析接口；当前默认关闭。"""

from .contracts import (
    FundamentalAnalyzer,
    FundamentalInput,
    FundamentalResult,
)
from .disabled import DisabledFundamentalAnalyzer

__all__ = [
    "DisabledFundamentalAnalyzer",
    "FundamentalAnalyzer",
    "FundamentalInput",
    "FundamentalResult",
]
