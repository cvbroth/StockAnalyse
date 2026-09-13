"""第一层分析的兼容公开接口。

新代码由 ``AnalysisEngine`` 和 ``Layer1Analyzer`` 分层执行；本模块保留旧函数名，
避免现有命令、测试和第三方调用在重构后失效。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .contracts import StockInput
from .layer1.breakout_retest import evaluate_breakout_retest
from .layer1.common import (
    aligned_returns,
    is_supported_a_share,
    normalize_code,
    parse_yyyymmdd,
    period_return,
    to_tx_symbol,
)
from .layer1.filters import basic_filters
from .layer1.ma_trend import evaluate_ma_trend
from .layer1.price_structure import evaluate_price_structure
from .layer1.relative_strength import (
    apply_market_percentiles,
    evaluate_relative_strength_base,
    mark_percentile_not_required,
)
from .layer1.scoring import refresh_score
from .layer1.volume_price import evaluate_volume_price
from .models import ScreenConfig
from .pipeline import AnalysisEngine


_DEFAULT_ENGINE = AnalysisEngine()


def analyze_stock(
    code: str,
    name: str,
    df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
    end_date: str,
    config: ScreenConfig,
) -> dict[str, Any]:
    """运行第一层并返回与v1.2完全兼容的字典结果。"""

    stock = StockInput(
        code=code,
        name=name,
        bars=df,
        benchmark=benchmark_df,
        end_date=end_date,
    )
    return _DEFAULT_ENGINE.analyze(stock, config).to_record()


__all__ = [
    "aligned_returns",
    "analyze_stock",
    "apply_market_percentiles",
    "basic_filters",
    "evaluate_breakout_retest",
    "evaluate_ma_trend",
    "evaluate_price_structure",
    "evaluate_relative_strength_base",
    "evaluate_volume_price",
    "is_supported_a_share",
    "mark_percentile_not_required",
    "normalize_code",
    "parse_yyyymmdd",
    "period_return",
    "refresh_score",
    "to_tx_symbol",
]
