"""基本面数据收集配置读取与校验。"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_FUNDAMENTAL_CONFIG_PATH = (
    PROJECT_DIR / "config" / "analysis" / "fundamental.toml"
)


@dataclass(frozen=True)
class FundamentalCollectionConfig:
    financial_top_n: int = 30
    research_top_n: int = 10
    quarters: int = 8
    stale_after_days: int = 7


@dataclass(frozen=True)
class FundamentalScoringConfig:
    earnings_momentum_weight: float = 25.0
    business_quality_weight: float = 20.0
    industry_cycle_weight: float = 15.0
    expectation_delta_weight: float = 25.0
    risk_penalty_weight: float = 15.0
    red_risk_threshold: float = 80.0
    key_focus_threshold: float = 75.0
    follow_up_threshold: float = 60.0
    min_research_confidence: float = 0.60


@dataclass(frozen=True)
class FundamentalSettings:
    version: str
    enabled: bool
    provider: str
    collection: FundamentalCollectionConfig
    scoring: FundamentalScoringConfig
    path: Path


def load_fundamental_settings(
    path: Path | None = None,
) -> FundamentalSettings:
    config_path = (path or DEFAULT_FUNDAMENTAL_CONFIG_PATH).expanduser().resolve()
    if not config_path.is_file():
        raise RuntimeError(f"基本面配置不存在：{config_path}")
    try:
        with config_path.open("rb") as handle:
            payload = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeError(f"基本面配置读取失败：{config_path}：{exc}") from exc

    version = payload.get("version")
    if not isinstance(version, str) or not version.strip():
        raise RuntimeError("基本面配置必须提供非空 version")
    enabled = payload.get("enabled")
    provider = payload.get("provider")
    values = payload.get("collection")
    scoring_values = payload.get("scoring")
    if not isinstance(enabled, bool):
        raise RuntimeError("基本面配置 enabled 必须是布尔值")
    if not isinstance(provider, str) or not provider.strip():
        raise RuntimeError("基本面配置 provider 不能为空")
    if not isinstance(values, dict):
        raise RuntimeError("基本面配置必须提供 [collection] 区段")
    if not isinstance(scoring_values, dict):
        raise RuntimeError("基本面配置必须提供 [scoring] 区段")
    expected = {
        "financial_top_n", "research_top_n", "quarters", "stale_after_days"
    }
    unknown = sorted(set(values).difference(expected))
    missing = sorted(expected.difference(values))
    if unknown:
        raise RuntimeError(f"基本面[collection]包含未知参数：{', '.join(unknown)}")
    if missing:
        raise RuntimeError(f"基本面[collection]缺少参数：{', '.join(missing)}")
    try:
        collection = FundamentalCollectionConfig(
            financial_top_n=int(values["financial_top_n"]),
            research_top_n=int(values["research_top_n"]),
            quarters=int(values["quarters"]),
            stale_after_days=int(values["stale_after_days"]),
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"基本面收集配置无效：{exc}") from exc
    if collection.financial_top_n < 1:
        raise RuntimeError("financial_top_n 必须至少为1")
    if not 1 <= collection.research_top_n <= collection.financial_top_n:
        raise RuntimeError("research_top_n 必须在1到financial_top_n之间")
    if collection.quarters < 1:
        raise RuntimeError("quarters 必须至少为1")
    if collection.stale_after_days < 0:
        raise RuntimeError("stale_after_days 不能为负数")
    if enabled and provider == "none":
        raise RuntimeError("启用基本面时 provider 不能是 none")

    scoring_expected = {
        "earnings_momentum_weight",
        "business_quality_weight",
        "industry_cycle_weight",
        "expectation_delta_weight",
        "risk_penalty_weight",
        "red_risk_threshold",
        "key_focus_threshold",
        "follow_up_threshold",
        "min_research_confidence",
    }
    scoring_unknown = sorted(set(scoring_values).difference(scoring_expected))
    scoring_missing = sorted(scoring_expected.difference(scoring_values))
    if scoring_unknown:
        raise RuntimeError(
            f"基本面[scoring]包含未知参数：{', '.join(scoring_unknown)}"
        )
    if scoring_missing:
        raise RuntimeError(
            f"基本面[scoring]缺少参数：{', '.join(scoring_missing)}"
        )
    try:
        scoring = FundamentalScoringConfig(
            **{key: float(scoring_values[key]) for key in scoring_expected}
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"基本面合并评分配置无效：{exc}") from exc
    weights = (
        scoring.earnings_momentum_weight,
        scoring.business_quality_weight,
        scoring.industry_cycle_weight,
        scoring.expectation_delta_weight,
        scoring.risk_penalty_weight,
    )
    if any(weight < 0 for weight in weights) or abs(sum(weights) - 100.0) > 1e-9:
        raise RuntimeError("基本面四项正向权重与风险惩罚权重之和必须为100")
    if sum(weights[:4]) <= 0:
        raise RuntimeError("基本面正向权重之和必须大于0")
    for name in (
        "red_risk_threshold",
        "key_focus_threshold",
        "follow_up_threshold",
    ):
        value = getattr(scoring, name)
        if not 0.0 <= value <= 100.0:
            raise RuntimeError(f"{name} 必须位于0到100之间")
    if scoring.follow_up_threshold > scoring.key_focus_threshold:
        raise RuntimeError("follow_up_threshold 不能高于 key_focus_threshold")
    if not 0.0 <= scoring.min_research_confidence <= 1.0:
        raise RuntimeError("min_research_confidence 必须位于0到1之间")
    return FundamentalSettings(
        version=version.strip(),
        enabled=enabled,
        provider=provider.strip(),
        collection=collection,
        scoring=scoring,
        path=config_path,
    )
