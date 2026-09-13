"""分析流水线各层共享的标准输入、输出协议。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import pandas as pd

from .models import ScreenConfig


@dataclass(frozen=True)
class StockInput:
    """单只股票的一次只读分析输入。"""

    code: str
    name: str
    bars: pd.DataFrame
    benchmark: pd.DataFrame
    end_date: str


@dataclass(frozen=True)
class ConditionResult:
    """第一层单项条件的标准结果。"""

    passed: bool
    detail: dict[str, Any]

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "ConditionResult":
        return cls(
            passed=bool(record["passed"]),
            detail=dict(record.get("detail", {})),
        )

    def to_record(self) -> dict[str, Any]:
        return {"passed": self.passed, "detail": dict(self.detail)}


class AnalysisModule(Protocol):
    """所有第一层分析模块都遵循的接口。"""

    name: str

    def analyze(
        self,
        stock: StockInput,
        config: ScreenConfig,
    ) -> ConditionResult: ...


@dataclass(frozen=True)
class Layer1Result:
    """第一层完整结果；可转换为旧版兼容字典。"""

    stock: StockInput
    tx_symbol: str | None
    base_filters: dict[str, Any]
    conditions: dict[str, ConditionResult]
    metrics: dict[str, Any]
    technical_score: int
    technical_score_max: int
    technical_pass: bool
    tier: str

    def to_record(self) -> dict[str, Any]:
        return {
            "code": self.stock.code,
            "name": self.stock.name,
            "tx_symbol": self.tx_symbol,
            "as_of_date": self.stock.bars["date"].iloc[-1],
            "base_filters": dict(self.base_filters),
            "conditions": {
                key: result.to_record() for key, result in self.conditions.items()
            },
            "metrics": dict(self.metrics),
            "technical_score": self.technical_score,
            "technical_score_max": self.technical_score_max,
            "technical_pass": self.technical_pass,
            "tier": self.tier,
        }
