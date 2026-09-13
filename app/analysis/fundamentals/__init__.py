"""基本面结果契约与不依赖数据源的纯量化模块。"""

from .contracts import (
    FUNDAMENTAL_RESULT_SCHEMA_VERSION,
    FundamentalAnalyzer,
    FundamentalEvidence,
    FundamentalInput,
    FundamentalResult,
)
from .disabled import DisabledFundamentalAnalyzer
from .financial import FinancialQuantResult, analyze_financial_observations

__all__ = [
    "DisabledFundamentalAnalyzer",
    "FUNDAMENTAL_RESULT_SCHEMA_VERSION",
    "FundamentalAnalyzer",
    "FundamentalEvidence",
    "FundamentalInput",
    "FundamentalResult",
    "FinancialQuantResult",
    "analyze_financial_observations",
]
