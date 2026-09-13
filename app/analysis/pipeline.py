"""分层分析流水线统一入口。"""

from __future__ import annotations

from .contracts import Layer1Result, StockInput
from .fundamentals import (
    DisabledFundamentalAnalyzer,
    FundamentalAnalyzer,
    FundamentalInput,
    FundamentalResult,
)
from .layer1 import Layer1Analyzer
from .layer2 import Layer2Analyzer, Layer2Config, Layer2Result
from .models import ScreenConfig


class AnalysisEngine:
    """统一编排入口；第一阶段仅注册资格筛选层。"""

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
