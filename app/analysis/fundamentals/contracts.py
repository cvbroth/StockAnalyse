"""基本面层的标准输入、输出和提供者协议。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ...fundamentals.models import normalize_date


FUNDAMENTAL_RESULT_SCHEMA_VERSION = "fundamental-result-v2"
FUNDAMENTAL_RESEARCH_SCHEMA_VERSION = "fundamental-research-v1"
FUNDAMENTAL_STATES = {
    "IMPROVING", "STABLE", "DETERIORATING", "UNCERTAIN"
}
RESULT_STATUSES = {
    "disabled", "pending", "complete", "partial", "failed", "rejected"
}
RESEARCH_STATUSES = {"complete", "partial", "failed"}
RISK_LEVELS = {"LOW", "MEDIUM", "HIGH", "RED", "UNKNOWN"}
RESEARCH_SIGNAL_NAMES = {
    "revenue_accelerating",
    "profit_accelerating",
    "margin_improving",
    "industry_improving",
    "expectation_revision",
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
    source_tier: int = 4
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
        if int(self.source_tier) not in {1, 2, 3, 4}:
            raise ValueError("证据 source_tier 必须是1到4")
        object.__setattr__(self, "confidence", float(self.confidence))
        object.__setattr__(self, "source_tier", int(self.source_tier))
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
            "source_tier": int(self.source_tier),
            "source_url": self.source_url,
            "document_id": self.document_id,
            "excerpt": self.excerpt,
        }


@dataclass(frozen=True)
class FundamentalResearchResult:
    """外部研究员返回的结构化结果；不包含Python已计算的财务分。"""

    run_id: str
    input_hash: str
    code: str
    name: str
    as_of_date: str
    status: str
    fundamental_state: str
    industry_cycle_score: float | None
    expectation_delta_score: float | None
    risk_score: float | None
    risk_level: str
    confidence: float
    signals: dict[str, bool | None]
    catalysts: tuple[str, ...]
    risks: tuple[str, ...]
    vetoes: tuple[str, ...]
    evidence: tuple[FundamentalEvidence | dict[str, Any], ...]
    why_now: str
    industry_summary: str
    expectation_summary: str
    risk_summary: str
    schema_version: str = FUNDAMENTAL_RESEARCH_SCHEMA_VERSION

    def __post_init__(self) -> None:
        code = str(self.code).zfill(6)
        if len(code) != 6 or not code.isdigit():
            raise ValueError(f"研究结果股票代码无效：{self.code!r}")
        if not str(self.run_id).strip():
            raise ValueError("研究结果 run_id 不能为空")
        if not str(self.name).strip():
            raise ValueError("研究结果 name 不能为空")
        if self.schema_version != FUNDAMENTAL_RESEARCH_SCHEMA_VERSION:
            raise ValueError(
                f"研究结果 schema_version 不兼容：{self.schema_version}"
            )
        if self.status not in RESEARCH_STATUSES:
            raise ValueError(f"研究结果状态无效：{self.status}")
        if self.fundamental_state not in FUNDAMENTAL_STATES:
            raise ValueError(
                f"研究结果基本面状态无效：{self.fundamental_state}"
            )
        if self.risk_level not in RISK_LEVELS:
            raise ValueError(f"研究结果风险等级无效：{self.risk_level}")
        if len(self.input_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.input_hash
        ):
            raise ValueError("研究结果 input_hash 必须是64位小写SHA-256")
        as_of_date = normalize_date(self.as_of_date, "as_of_date")
        for field_name in (
            "industry_cycle_score",
            "expectation_delta_score",
            "risk_score",
        ):
            value = getattr(self, field_name)
            if value is not None and not 0.0 <= float(value) <= 100.0:
                raise ValueError(f"{field_name} 必须位于0到100之间")
            if value is not None:
                object.__setattr__(self, field_name, float(value))
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("研究结果 confidence 必须位于0到1之间")
        unknown_signals = sorted(set(self.signals).difference(RESEARCH_SIGNAL_NAMES))
        if unknown_signals:
            raise ValueError(f"研究结果包含未知signals：{', '.join(unknown_signals)}")
        if any(
            value is not True and value is not False and value is not None
            for value in self.signals.values()
        ):
            raise ValueError("研究结果 signals 的值必须是true、false或null")
        normalized_evidence: list[FundamentalEvidence] = []
        for item in self.evidence:
            evidence = (
                item
                if isinstance(item, FundamentalEvidence)
                else FundamentalEvidence(**item)
                if isinstance(item, dict)
                else None
            )
            if evidence is None:
                raise ValueError("研究证据必须是 FundamentalEvidence 或字典")
            if evidence.published_date > as_of_date:
                raise ValueError("研究证据发布日期晚于运行截止日")
            normalized_evidence.append(evidence)
        if self.status == "complete":
            if any(
                getattr(self, field_name) is None
                for field_name in (
                    "industry_cycle_score",
                    "expectation_delta_score",
                    "risk_score",
                )
            ):
                raise ValueError("complete研究结果必须提供行业、预期和风险三项分数")
            if not normalized_evidence:
                raise ValueError("complete研究结果必须至少提供一条证据")
            if set(self.signals) != RESEARCH_SIGNAL_NAMES:
                raise ValueError("complete研究结果必须回答全部固定signals")
            if any(value is None for value in self.signals.values()):
                raise ValueError("complete研究结果的signals不能包含null")
            if not self.risks:
                raise ValueError("complete研究结果必须至少列出一项风险")
            for field_name in (
                "why_now",
                "industry_summary",
                "expectation_summary",
                "risk_summary",
            ):
                if not str(getattr(self, field_name)).strip():
                    raise ValueError(f"complete研究结果必须提供 {field_name}")
        if (self.vetoes or self.risk_level == "RED") and not normalized_evidence:
            raise ValueError("风险否决或RED等级必须提供证据")
        for field_name in ("catalysts", "risks", "vetoes"):
            values = tuple(str(value).strip() for value in getattr(self, field_name))
            if any(not value for value in values):
                raise ValueError(f"研究结果 {field_name} 不能包含空字符串")
            object.__setattr__(self, field_name, values)
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "as_of_date", as_of_date)
        object.__setattr__(self, "confidence", float(self.confidence))
        object.__setattr__(self, "evidence", tuple(normalized_evidence))

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "FundamentalResearchResult":
        scores = record.get("scores")
        if not isinstance(scores, dict):
            raise ValueError("研究结果必须提供 scores 对象")
        expected_scores = {"industry_cycle", "expectation_delta", "risk"}
        if set(scores) != expected_scores:
            raise ValueError("研究结果 scores 必须且只能包含行业、预期变化和风险")
        return cls(
            run_id=str(record.get("run_id", "")),
            input_hash=str(record.get("input_hash", "")),
            code=str(record.get("code", "")),
            name=str(record.get("name", "")),
            as_of_date=str(record.get("as_of_date", "")),
            status=str(record.get("status", "")),
            fundamental_state=str(record.get("fundamental_state", "")),
            industry_cycle_score=scores["industry_cycle"],
            expectation_delta_score=scores["expectation_delta"],
            risk_score=scores["risk"],
            risk_level=str(record.get("risk_level", "UNKNOWN")),
            confidence=float(record.get("confidence", 0.0)),
            signals=dict(record.get("signals") or {}),
            catalysts=tuple(record.get("catalysts") or ()),
            risks=tuple(record.get("risks") or ()),
            vetoes=tuple(record.get("vetoes") or ()),
            evidence=tuple(record.get("evidence") or ()),
            why_now=str(record.get("why_now", "")),
            industry_summary=str(record.get("industry_summary", "")),
            expectation_summary=str(record.get("expectation_summary", "")),
            risk_summary=str(record.get("risk_summary", "")),
            schema_version=str(record.get("schema_version", "")),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "input_hash": self.input_hash,
            "code": self.code,
            "name": self.name,
            "as_of_date": self.as_of_date,
            "status": self.status,
            "fundamental_state": self.fundamental_state,
            "scores": {
                "industry_cycle": self.industry_cycle_score,
                "expectation_delta": self.expectation_delta_score,
                "risk": self.risk_score,
            },
            "risk_level": self.risk_level,
            "confidence": float(self.confidence),
            "signals": dict(self.signals),
            "catalysts": list(self.catalysts),
            "risks": list(self.risks),
            "vetoes": list(self.vetoes),
            "evidence": [item.to_record() for item in self.evidence],
            "why_now": self.why_now,
            "industry_summary": self.industry_summary,
            "expectation_summary": self.expectation_summary,
            "risk_summary": self.risk_summary,
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
