"""将Python财务量化与外部结构化研究合并为可解释的Layer3结果。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable

from ...fundamentals import FundamentalScoringConfig
from .contracts import FundamentalResearchResult


@dataclass(frozen=True)
class Layer3Result:
    code: str
    name: str
    status: str
    fundamental_state: str
    focus_status: str
    scores: dict[str, float | None]
    positive_score: float | None
    risk_penalty: float | None
    final_score: float | None
    confidence: float | None
    vetoes: tuple[str, ...]
    catalysts: tuple[str, ...]
    risks: tuple[str, ...]
    rank: int | None = None

    def to_record(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "status": self.status,
            "fundamental_state": self.fundamental_state,
            "focus_status": self.focus_status,
            "scores": dict(self.scores),
            "positive_score": self.positive_score,
            "risk_penalty": self.risk_penalty,
            "final_score": self.final_score,
            "confidence": self.confidence,
            "vetoes": list(self.vetoes),
            "catalysts": list(self.catalysts),
            "risks": list(self.risks),
            "rank": self.rank,
        }


def compose_layer3_result(
    financial_record: dict[str, Any],
    research: FundamentalResearchResult | None,
    config: FundamentalScoringConfig,
) -> Layer3Result:
    """合并单只股票；缺少研究时不生成最终分。"""

    financial = financial_record.get("financial_quant") or {}
    financial_scores = financial.get("scores") or {}
    earnings = financial_scores.get("earnings_momentum")
    business = financial_scores.get("business_quality")
    financial_state = str(financial.get("fundamental_state", "UNCERTAIN"))
    scores: dict[str, float | None] = {
        "earnings_momentum": earnings,
        "business_quality": business,
        "industry_cycle": (
            research.industry_cycle_score if research is not None else None
        ),
        "expectation_delta": (
            research.expectation_delta_score if research is not None else None
        ),
        "risk": research.risk_score if research is not None else None,
    }
    if research is None:
        return Layer3Result(
            code=str(financial_record["code"]),
            name=str(financial_record.get("name", "")),
            status="pending",
            fundamental_state=financial_state,
            focus_status="PENDING_RESEARCH",
            scores=scores,
            positive_score=None,
            risk_penalty=None,
            final_score=None,
            confidence=None,
            vetoes=(),
            catalysts=(),
            risks=(),
        )

    vetoes = list(research.vetoes)
    if research.risk_level == "RED":
        vetoes.append("研究风险等级为RED")
    elif (
        research.status == "complete"
        and research.risk_score is not None
        and research.risk_score >= config.red_risk_threshold
    ):
        vetoes.append(
            f"风险达到RED阈值（{float(research.risk_score):.1f}）"
        )
    vetoes = list(dict.fromkeys(vetoes))
    state = (
        research.fundamental_state
        if research.fundamental_state != "UNCERTAIN"
        else financial_state
    )
    if vetoes:
        status = "rejected"
    elif research.status == "failed":
        status = "failed"
    elif financial.get("status") != "complete":
        status = "partial"
    elif research.status != "complete" or any(
        value is None for value in scores.values()
    ):
        status = "partial"
    elif research.confidence < config.min_research_confidence:
        status = "partial"
    else:
        status = "complete"

    positive_score: float | None = None
    risk_penalty: float | None = None
    final_score: float | None = None
    positive_values = {
        "earnings_momentum": (
            earnings,
            config.earnings_momentum_weight,
        ),
        "business_quality": (
            business,
            config.business_quality_weight,
        ),
        "industry_cycle": (
            research.industry_cycle_score,
            config.industry_cycle_weight,
        ),
        "expectation_delta": (
            research.expectation_delta_score,
            config.expectation_delta_weight,
        ),
    }
    if all(value is not None for value, _ in positive_values.values()):
        positive_weight = sum(weight for _, weight in positive_values.values())
        positive_score = round(
            sum(float(value) * weight for value, weight in positive_values.values())
            / positive_weight,
            4,
        )
    if research.risk_score is not None:
        risk_penalty = round(
            float(research.risk_score) * config.risk_penalty_weight / 100.0,
            4,
        )
    if status in {"complete", "rejected"} and positive_score is not None:
        final_score = round(
            max(0.0, positive_score - float(risk_penalty or 0.0)),
            4,
        )
    coverage = financial.get("data_coverage")
    confidence = (
        round((float(coverage) + research.confidence) / 2.0, 4)
        if coverage is not None
        else round(research.confidence, 4)
    )
    if status == "rejected":
        focus_status = "REJECTED"
    elif status != "complete" or final_score is None:
        focus_status = "PENDING_REVIEW"
    elif final_score >= config.key_focus_threshold and state == "IMPROVING":
        focus_status = "KEY_FOCUS"
    elif final_score >= config.follow_up_threshold:
        focus_status = "FOLLOW_UP"
    else:
        focus_status = "WATCH"
    return Layer3Result(
        code=str(financial_record["code"]),
        name=str(financial_record.get("name", "")),
        status=status,
        fundamental_state=state,
        focus_status=focus_status,
        scores=scores,
        positive_score=positive_score,
        risk_penalty=risk_penalty,
        final_score=final_score,
        confidence=confidence,
        vetoes=tuple(vetoes),
        catalysts=research.catalysts,
        risks=research.risks,
    )


def rank_layer3_results(results: Iterable[Layer3Result]) -> list[Layer3Result]:
    """只给完成且未否决的结果排名，其他记录保留但没有名次。"""

    materialized = list(results)
    eligible = sorted(
        (
            item
            for item in materialized
            if item.status == "complete" and item.final_score is not None
        ),
        key=lambda item: (float(item.final_score), float(item.confidence or 0.0)),
        reverse=True,
    )
    rank_by_code = {item.code: index for index, item in enumerate(eligible, 1)}
    ranked = [replace(item, rank=rank_by_code.get(item.code)) for item in materialized]
    return sorted(
        ranked,
        key=lambda item: (
            item.rank is not None,
            -(item.rank or 10**9),
        ),
        reverse=True,
    )
