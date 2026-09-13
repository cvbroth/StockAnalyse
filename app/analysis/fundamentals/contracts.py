"""基本面层的标准输入、输出和提供者协议。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class FundamentalInput:
    code: str
    name: str
    as_of_date: str
    technical_quality_score: float
    technical_record: dict[str, Any]


@dataclass(frozen=True)
class FundamentalResult:
    status: str
    provider: str
    scores: dict[str, float]
    vetoes: tuple[str, ...]
    evidence: tuple[dict[str, Any], ...]
    note: str | None = None

    def to_record(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "provider": self.provider,
            "scores": dict(self.scores),
            "vetoes": list(self.vetoes),
            "evidence": [dict(item) for item in self.evidence],
            "note": self.note,
        }


class FundamentalAnalyzer(Protocol):
    name: str

    def analyze(self, stock: FundamentalInput) -> FundamentalResult: ...
