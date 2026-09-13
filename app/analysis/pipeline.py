"""分层分析流水线统一入口。"""

from __future__ import annotations

from ..fundamentals import FundamentalScoringConfig
from .contracts import Layer1Result, StockInput
from .fundamentals import (
    DisabledFundamentalAnalyzer,
    FundamentalAnalyzer,
    FundamentalInput,
    FundamentalResearchResult,
    FundamentalResult,
    Layer3Result,
    compose_layer3_result,
)
from .layer1 import Layer1Analyzer
from .layer2 import Layer2Analyzer, Layer2Config, Layer2Result
from .models import ScreenConfig


class AnalysisEngine:
    """资格、技术质量和Layer3基本面合并的统一纯分析入口。"""

    def __init__(
        self,
        layer1: Layer1Analyzer | None = None,
        fundamental: FundamentalAnalyzer | None = None,
    ) -> None:
        self.layer1 = layer1 or Layer1Analyzer()
        self.layer2 = Layer2Analyzer()
        self.fundamental = fundamental or DisabledFundamentalAnalyzer()

    def analyze(
        self,
        stock: StockInput,
        config: ScreenConfig,
    ) -> Layer1Result:
        return self.layer1.analyze(stock, config)

    def analyze_quality(
        self,
        layer1_record: dict,
        config: Layer2Config,
    ) -> Layer2Result:
        return self.layer2.analyze(layer1_record, config)

    def analyze_fundamentals(
        self,
        stock: FundamentalInput,
    ) -> FundamentalResult:
        return self.fundamental.analyze(stock)

    def analyze_layer3(
        self,
        financial_record: dict,
        research: FundamentalResearchResult | None,
        config: FundamentalScoringConfig,
    ) -> Layer3Result:
        """合并财务量化和已校验研究；缺少研究时返回pending。"""

        return compose_layer3_result(financial_record, research, config)
