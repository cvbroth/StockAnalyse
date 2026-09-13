"""基本面层的标准输入、输出和提供者协议。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...fundamentals.models import normalize_date


FUNDAMENTAL_RESULT_SCHEMA_VERSION = "fundamental-result-v2"
FUNDAMENTAL_STATES = {
    "IMPROVING", "STABLE", "DETERIORATING", "UNCERTAIN"
}
RESULT_STATUSES = {
    "disabled", "pending", "complete", "partial", "failed", "rejected"
}


@dataclass(frozen=True)
class FundamentalEvidence:
    """一条可追溯的基本面判断证据。"""

    claim: str
    source_type: str
    source_name: str
    published_date: str
    effective_period: str
    confidence: float
    source_url: str | None = None
    document_id: str | None = None
    excerpt: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "claim", "source_type", "source_name", "effective_period"
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"证据字段 {field_name} 不能为空")
        if not self.source_url and not self.document_id:
            raise ValueError("证据必须提供 source_url 或 document_id")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("证据 confidence 必须位于0到1之间")
        object.__setattr__(
            self,
            "published_date",
            normalize_date(self.published_date, "published_date"),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "source_type": self.source_type,
            "source_name": self.source_name,
            "published_date": self.published_date,
            "effective_period": self.effective_period,
            "confidence": float(self.confidence),
            "source_url": self.source_url,
            "document_id": self.document_id,
            "excerpt": self.excerpt,
        }


@dataclass(frozen=True)
class FundamentalInput:
    code: str
    name: str
    as_of_date: str
    technical_quality_score: float
    technical_record: dict[str, Any]
    run_id: str | None = None
    data_cutoff_date: str | None = None
    data_coverage: float | None = None


@dataclass(frozen=True)
class FundamentalResult:
    status: str
    provider: str
    scores: dict[str, float]
    vetoes: tuple[str, ...]
    evidence: tuple[FundamentalEvidence | dict[str, Any], ...]
    note: str | None = None
    fundamental_state: str | None = None
    data_coverage: float | None = None
    confidence: float | None = None
    schema_version: str = FUNDAMENTAL_RESULT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.status not in RESULT_STATUSES:
            raise ValueError(f"基本面结果状态无效：{self.status}")
        if (
            self.fundamental_state is not None
            and self.fundamental_state not in FUNDAMENTAL_STATES
        ):
            raise ValueError(f"基本面状态无效：{self.fundamental_state}")
        for field_name in ("data_coverage", "confidence"):
            value = getattr(self, field_name)
            if value is not None and not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{field_name} 必须位于0到1之间")
        normalized_evidence: list[FundamentalEvidence] = []
        for item in self.evidence:
            if isinstance(item, FundamentalEvidence):
                normalized_evidence.append(item)
            elif isinstance(item, dict):
                normalized_evidence.append(FundamentalEvidence(**item))
            else:
                raise ValueError("evidence 必须是 FundamentalEvidence 或字典")
        object.__setattr__(self, "evidence", tuple(normalized_evidence))

    def to_record(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "provider": self.provider,
            "scores": dict(self.scores),
            "vetoes": list(self.vetoes),
            "evidence": [item.to_record() for item in self.evidence],
            "note": self.note,
            "fundamental_state": self.fundamental_state,
            "data_coverage": self.data_coverage,
            "confidence": self.confidence,
            "schema_version": self.schema_version,
        }


class FundamentalAnalyzer(Protocol):
    name: str

    def analyze(self, stock: FundamentalInput) -> FundamentalResult: ...
