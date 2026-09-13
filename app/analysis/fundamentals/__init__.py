"""基本面结果契约与不依赖数据源的纯量化模块。"""

from .contracts import (
    FUNDAMENTAL_RESEARCH_SCHEMA_VERSION,
    FUNDAMENTAL_RESULT_SCHEMA_VERSION,
    FundamentalAnalyzer,
    FundamentalEvidence,
    FundamentalInput,
    FundamentalResearchResult,
    FundamentalResult,
)
from .disabled import DisabledFundamentalAnalyzer
from .financial import FinancialQuantResult, analyze_financial_observations
from .layer3 import Layer3Result, compose_layer3_result, rank_layer3_results

__all__ = [
    "DisabledFundamentalAnalyzer",
    "FUNDAMENTAL_RESEARCH_SCHEMA_VERSION",
    "FUNDAMENTAL_RESULT_SCHEMA_VERSION",
    "FundamentalAnalyzer",
    "FundamentalEvidence",
    "FundamentalInput",
    "FundamentalResearchResult",
    "FundamentalResult",
    "FinancialQuantResult",
    "Layer3Result",
    "analyze_financial_observations",
    "compose_layer3_result",
    "rank_layer3_results",
]
