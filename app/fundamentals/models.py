"""跨提供者、存储和同步服务使用的基本面数据契约。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


FUNDAMENTAL_DATA_SCHEMA_VERSION = "fundamental-data-v2"
AVAILABILITY_BASES = {"reported", "conservative_deadline", "retrieved_at"}


def normalize_date(value: str, field_name: str) -> str:
    """接受 YYYYMMDD/ISO 日期并统一为 YYYY-MM-DD。"""

    raw = str(value).strip()
    for pattern in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(raw, pattern).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"{field_name} 必须是 YYYY-MM-DD 或 YYYYMMDD：{value!r}")


@dataclass(frozen=True)
class FundamentalFetchRequest:
    """一次由技术候选结果驱动的基本面数据需求。"""

    run_id: str
    code: str
    name: str
    as_of_date: str
    requested_quarters: int
    technical_score: int
    technical_quality_score: float
    quality_rank: int | None
    selection_reason: str

    def __post_init__(self) -> None:
        code = str(self.code).zfill(6)
        if len(code) != 6 or not code.isdigit():
            raise ValueError(f"股票代码无效：{self.code!r}")
        if not str(self.run_id).strip():
            raise ValueError("run_id 不能为空")
        if self.requested_quarters < 1:
            raise ValueError("requested_quarters 必须至少为1")
        if not 0 <= int(self.technical_score) <= 5:
            raise ValueError("technical_score 必须位于0到5之间")
        object.__setattr__(self, "code", code)
        object.__setattr__(
            self,
            "as_of_date",
            normalize_date(self.as_of_date, "as_of_date"),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "code": self.code,
            "name": self.name,
            "as_of_date": self.as_of_date,
            "requested_quarters": self.requested_quarters,
            "technical_score": self.technical_score,
            "technical_quality_score": self.technical_quality_score,
            "quality_rank": self.quality_rank,
            "selection_reason": self.selection_reason,
        }


@dataclass(frozen=True)
class FundamentalObservation:
    """一个带时间边界和来源的标准化财务观测值。"""

    code: str
    metric: str
    period_end: str
    published_date: str
    available_at: str
    value: float | None
    unit: str
    source: str
    source_record_id: str
    availability_basis: str = "reported"

    def __post_init__(self) -> None:
        code = str(self.code).zfill(6)
        if len(code) != 6 or not code.isdigit():
            raise ValueError(f"股票代码无效：{self.code!r}")
        for field_name in ("metric", "unit", "source", "source_record_id"):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} 不能为空")
        period_end = normalize_date(self.period_end, "period_end")
        published_date = normalize_date(self.published_date, "published_date")
        available_at = normalize_date(self.available_at, "available_at")
        if available_at < published_date:
            raise ValueError("available_at 不能早于 published_date")
        if self.availability_basis not in AVAILABILITY_BASES:
            raise ValueError(
                f"availability_basis 无效：{self.availability_basis!r}"
            )
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "period_end", period_end)
        object.__setattr__(self, "published_date", published_date)
        object.__setattr__(self, "available_at", available_at)
        if self.value is not None:
            object.__setattr__(self, "value", float(self.value))

    def to_record(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "metric": self.metric,
            "period_end": self.period_end,
            "published_date": self.published_date,
            "available_at": self.available_at,
            "value": self.value,
            "unit": self.unit,
            "source": self.source,
            "source_record_id": self.source_record_id,
            "availability_basis": self.availability_basis,
        }


@dataclass(frozen=True)
class FundamentalDataset:
    """提供者返回的单只股票标准数据集。"""

    provider: str
    code: str
    as_of_date: str
    observations: tuple[FundamentalObservation, ...]

    def __post_init__(self) -> None:
        code = str(self.code).zfill(6)
        cutoff = normalize_date(self.as_of_date, "as_of_date")
        if not str(self.provider).strip():
            raise ValueError("provider 不能为空")
        for observation in self.observations:
            if observation.code != code:
                raise ValueError("数据集包含其他股票的观测值")
            if observation.available_at > cutoff:
                raise ValueError(
                    f"{observation.metric} 的 available_at 晚于分析截止日"
                )
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "as_of_date", cutoff)


def today_iso() -> str:
    return date.today().isoformat()
