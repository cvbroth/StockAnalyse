"""第一层五项技术条件的组合器。"""

from __future__ import annotations

from collections.abc import Iterable

from ..contracts import AnalysisModule, Layer1Result, StockInput
from ..models import CONDITION_KEYS, ScreenConfig
from .breakout_retest import BreakoutRetestModule
from .common import period_return, to_tx_symbol
from .filters import basic_filters
from .ma_trend import MATrendModule
from .price_structure import PriceStructureModule
from .scoring import score_summary
from .relative_strength import RelativeStrengthModule
from .volume_price import VolumePriceModule


DEFAULT_MODULES: tuple[AnalysisModule, ...] = (
    PriceStructureModule(),
    MATrendModule(),
    VolumePriceModule(),
    BreakoutRetestModule(),
    RelativeStrengthModule(),
)


class Layer1Analyzer:
    """按固定顺序运行五项条件，并返回标准第一层结果。"""

    def __init__(self, modules: Iterable[AnalysisModule] | None = None) -> None:
        self.modules = tuple(modules or DEFAULT_MODULES)
        names = tuple(module.name for module in self.modules)
        if names != CONDITION_KEYS:
            raise ValueError(
                "第一层模块必须按标准顺序完整提供："
                f"{', '.join(CONDITION_KEYS)}；实际为 {', '.join(names)}"
            )

    def analyze(
        self,
        stock: StockInput,
        config: ScreenConfig,
    ) -> Layer1Result:
        required_rows = max(
            config.min_history_days,
            config.breakout_lookback + config.breakout_search_days,
            71,
        )
        if len(stock.bars) < required_rows:
            raise ValueError(
                f"历史交易日不足：需要至少 {required_rows}，实际 {len(stock.bars)}"
            )

        condition_results = {
            module.name: module.analyze(stock, config) for module in self.modules
        }
        base_result = basic_filters(
            stock.code,
            stock.name,
            stock.bars,
            stock.end_date,
            config,
        )
        condition_records = {
            key: result.to_record() for key, result in condition_results.items()
        }
        score, score_max, technical_pass, tier = score_summary(
            base_result,
            condition_records,
        )
        return Layer1Result(
            stock=stock,
            tx_symbol=to_tx_symbol(stock.code),
            base_filters=base_result,
            conditions=condition_results,
            metrics={
                "close": float(stock.bars["close"].iloc[-1]),
                "return_20d": period_return(stock.bars["close"], 20),
                "return_60d": period_return(stock.bars["close"], 60),
            },
            technical_score=score,
            technical_score_max=score_max,
            technical_pass=technical_pass,
            tier=tier,
        )
