"""基本面层的标准输入、输出和提供者协议。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from ...fundamentals.models import normalize_date


FUNDAMENTAL_RESULT_SCHEMA_VERSION = "fundamental-result-v2"
FUNDAMENTAL_RESEARCH_SCHEMA_VERSION_V1 = "fundamental-research-v1"
FUNDAMENTAL_RESEARCH_SCHEMA_VERSION = "fundamental-research-v2"
FUNDAMENTAL_RESEARCH_SCHEMA_VERSIONS = {
    FUNDAMENTAL_RESEARCH_SCHEMA_VERSION_V1,
    FUNDAMENTAL_RESEARCH_SCHEMA_VERSION,
}
RESEARCH_SKILL_VERSION = "a-share-fundamental-v2.0"
RESEARCH_RUBRIC_VERSION = "layer3-research-rubric-v2.0"
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
RESEARCH_SOURCE_TYPES = {
    "filing",
    "investor_relations",
    "company",
    "industry",
    "government",
    "research",
    "media",
}
RESEARCH_QUALITY_FLAG_CODES = {
    "unit_ambiguity",
    "low_base_growth",
    "consolidation_scope_change",
    "plan_not_completed",
    "source_conflict",
    "stale_evidence",
    "date_ambiguity",
    "secondary_source_only",
    "other",
}
RESEARCH_BASE_SUPPORT_TARGETS = {
    "industry_cycle_score",
    "expectation_delta_score",
    "risk_score",
    "why_now",
    "industry_summary",
    "expectation_summary",
    "risk_summary",
}
_EVIDENCE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_INDEXED_SUPPORT_PATTERN = re.compile(r"^(catalysts|risks|vetoes)\.(\d+)$")


def _normalize_timestamp(value: str, field_name: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{field_name} 不能为空")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} 必须是ISO 8601时间") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} 必须包含时区")
    return parsed.isoformat(timespec="seconds")


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
    evidence_id: str | None = None
    source_title: str | None = None
    retrieved_at: str | None = None
    supports: tuple[str, ...] = ()

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
        supports = tuple(str(value).strip() for value in self.supports)
        if any(not value for value in supports):
            raise ValueError("证据 supports 不能包含空字符串")
        if len(set(supports)) != len(supports):
            raise ValueError("证据 supports 不能重复")
        object.__setattr__(self, "supports", supports)

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
            "evidence_id": self.evidence_id,
            "source_title": self.source_title,
            "retrieved_at": self.retrieved_at,
            "supports": list(self.supports),
        }


@dataclass(frozen=True)
class ResearchQualityFlag:
    """研究过程中发现的数据口径或证据质量异常。"""

    code: str
    detail: str
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        code = str(self.code).strip()
        detail = str(self.detail).strip()
        if code not in RESEARCH_QUALITY_FLAG_CODES:
            raise ValueError(f"未知数据质量标记：{code}")
        if not detail:
            raise ValueError("数据质量标记 detail 不能为空")
        evidence_ids = tuple(str(value).strip() for value in self.evidence_ids)
        if any(not value for value in evidence_ids):
            raise ValueError("数据质量标记 evidence_ids 不能包含空字符串")
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "detail", detail)
        object.__setattr__(self, "evidence_ids", evidence_ids)

    def to_record(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "detail": self.detail,
            "evidence_ids": list(self.evidence_ids),
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
    research_metadata: dict[str, str] | None = None
    quality_flags: tuple[ResearchQualityFlag | dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        code = str(self.code).zfill(6)
        if len(code) != 6 or not code.isdigit():
            raise ValueError(f"研究结果股票代码无效：{self.code!r}")
        if not str(self.run_id).strip():
            raise ValueError("研究结果 run_id 不能为空")
        if not str(self.name).strip():
            raise ValueError("研究结果 name 不能为空")
        if self.schema_version not in FUNDAMENTAL_RESEARCH_SCHEMA_VERSIONS:
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
        normalized_flags: list[ResearchQualityFlag] = []
        for item in self.quality_flags:
            flag = (
                item
                if isinstance(item, ResearchQualityFlag)
                else ResearchQualityFlag(**item)
                if isinstance(item, dict)
                else None
            )
            if flag is None:
                raise ValueError("数据质量标记必须是 ResearchQualityFlag 或字典")
            normalized_flags.append(flag)
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
            if (
                self.schema_version == FUNDAMENTAL_RESEARCH_SCHEMA_VERSION
                and len(values) > 3
            ):
                raise ValueError(f"研究结果 {field_name} 最多保留3项")
            if (
                self.schema_version == FUNDAMENTAL_RESEARCH_SCHEMA_VERSION
                and len(set(values)) != len(values)
            ):
                raise ValueError(f"研究结果 {field_name} 不能包含重复项")
            object.__setattr__(self, field_name, values)
        if self.schema_version == FUNDAMENTAL_RESEARCH_SCHEMA_VERSION:
            self._validate_v2(normalized_evidence, normalized_flags)
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "as_of_date", as_of_date)
        object.__setattr__(self, "confidence", float(self.confidence))
        object.__setattr__(self, "evidence", tuple(normalized_evidence))
        object.__setattr__(self, "quality_flags", tuple(normalized_flags))

    def _validate_v2(
        self,
        evidence_items: list[FundamentalEvidence],
        quality_flags: list[ResearchQualityFlag],
    ) -> None:
        metadata = self.research_metadata
        if not isinstance(metadata, dict):
            raise ValueError("v2研究结果必须提供 research_metadata 对象")
        required_metadata = {
            "skill_version",
            "rubric_version",
            "model_provider",
            "model_name",
            "started_at",
            "finished_at",
        }
        if set(metadata) != required_metadata:
            raise ValueError("research_metadata 字段不完整或包含未知字段")
        normalized_metadata = {
            key: str(value).strip() for key, value in metadata.items()
        }
        for key in (
            "skill_version",
            "rubric_version",
            "model_provider",
            "model_name",
        ):
            if not normalized_metadata[key]:
                raise ValueError(f"research_metadata.{key} 不能为空")
        started_at = _normalize_timestamp(
            normalized_metadata["started_at"],
            "research_metadata.started_at",
        )
        finished_at = _normalize_timestamp(
            normalized_metadata["finished_at"],
            "research_metadata.finished_at",
        )
        if datetime.fromisoformat(finished_at) < datetime.fromisoformat(
            started_at
        ):
            raise ValueError("研究结束时间不能早于开始时间")
        normalized_metadata["started_at"] = started_at
        normalized_metadata["finished_at"] = finished_at
        object.__setattr__(self, "research_metadata", normalized_metadata)

        evidence_by_id: dict[str, FundamentalEvidence] = {}
        supported: dict[str, list[FundamentalEvidence]] = {}
        for evidence in evidence_items:
            evidence_id = str(evidence.evidence_id or "").strip()
            if not _EVIDENCE_ID_PATTERN.fullmatch(evidence_id):
                raise ValueError("v2证据 evidence_id 格式无效")
            if evidence_id in evidence_by_id:
                raise ValueError(f"v2证据 evidence_id 重复：{evidence_id}")
            if evidence.source_type not in RESEARCH_SOURCE_TYPES:
                raise ValueError(f"v2证据 source_type 无效：{evidence.source_type}")
            if not str(evidence.source_title or "").strip():
                raise ValueError("v2证据 source_title 不能为空")
            if not str(evidence.excerpt or "").strip():
                raise ValueError(f"v2证据 {evidence_id} excerpt 不能为空")
            retrieved_at = _normalize_timestamp(
                str(evidence.retrieved_at or ""),
                f"证据 {evidence_id} retrieved_at",
            )
            if not evidence.supports:
                raise ValueError(f"v2证据 {evidence_id} 必须声明 supports")
            for target in evidence.supports:
                self._validate_support_target(target)
                supported.setdefault(target, []).append(evidence)
            object.__setattr__(evidence, "evidence_id", evidence_id)
            object.__setattr__(
                evidence,
                "source_title",
                str(evidence.source_title).strip(),
            )
            object.__setattr__(evidence, "retrieved_at", retrieved_at)
            evidence_by_id[evidence_id] = evidence

        for flag in quality_flags:
            unknown_ids = sorted(set(flag.evidence_ids).difference(evidence_by_id))
            if unknown_ids:
                raise ValueError(
                    f"数据质量标记引用未知 evidence_id：{', '.join(unknown_ids)}"
                )

        if self.status != "complete":
            return
        required_targets = set(RESEARCH_BASE_SUPPORT_TARGETS)
        required_targets.update(
            f"catalysts.{index}" for index, _ in enumerate(self.catalysts)
        )
        required_targets.update(
            f"risks.{index}" for index, _ in enumerate(self.risks)
        )
        required_targets.update(
            f"vetoes.{index}" for index, _ in enumerate(self.vetoes)
        )
        missing = sorted(required_targets.difference(supported))
        if missing:
            raise ValueError(f"v2研究结论缺少证据映射：{', '.join(missing)}")
        weak_targets = sorted(
            target
            for target in required_targets
            if all(item.source_tier == 4 for item in supported[target])
        )
        if weak_targets:
            raise ValueError(
                f"v2关键结论不能仅由四级来源支持：{', '.join(weak_targets)}"
            )
        direct_targets = (
            {f"vetoes.{index}" for index, _ in enumerate(self.vetoes)}
            | ({"risk_score"} if self.risk_level == "RED" else set())
        )
        indirect = sorted(
            target
            for target in direct_targets
            if all(item.source_tier > 2 for item in supported[target])
        )
        if indirect:
            raise ValueError(
                f"RED或否决结论必须有一至二级来源：{', '.join(indirect)}"
            )

    def _validate_support_target(self, target: str) -> None:
        if target in RESEARCH_BASE_SUPPORT_TARGETS:
            return
        if target.startswith("signals."):
            signal_name = target.removeprefix("signals.")
            if signal_name in RESEARCH_SIGNAL_NAMES:
                return
        match = _INDEXED_SUPPORT_PATTERN.fullmatch(target)
        if match is not None:
            collection_name, raw_index = match.groups()
            values = getattr(self, collection_name)
            if int(raw_index) < len(values):
                return
        raise ValueError(f"v2证据 supports 包含无效目标：{target}")

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "FundamentalResearchResult":
        schema_version = str(record.get("schema_version", ""))
        if (
            schema_version == FUNDAMENTAL_RESEARCH_SCHEMA_VERSION
            and "quality_flags" not in record
        ):
            raise ValueError("v2研究结果必须显式提供 quality_flags 数组")
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
            schema_version=schema_version,
            research_metadata=(
                dict(record["research_metadata"])
                if isinstance(record.get("research_metadata"), dict)
                else None
            ),
            quality_flags=tuple(record.get("quality_flags") or ()),
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
            "research_metadata": (
                dict(self.research_metadata)
                if self.research_metadata is not None
                else None
            ),
            "quality_flags": [item.to_record() for item in self.quality_flags],
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
