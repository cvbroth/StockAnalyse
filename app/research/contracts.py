"""研究执行层的提供者协议与执行摘要。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class ResearchResultProvider(Protocol):
    """从外部研究工具取得一只股票的结构化结果。"""

    name: str

    def load(self, request: dict[str, Any]) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class ResearchExecutionSummary:
    run_id: str
    provider: str
    total: int
    selected: int
    imported: int
    reused: int
    complete: int
    partial: int
    failed: int
    pending: int
    records: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def has_errors(self) -> bool:
        return self.failed > 0

    def to_record(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "provider": self.provider,
            "total": self.total,
            "selected": self.selected,
            "imported": self.imported,
            "reused": self.reused,
            "complete": self.complete,
            "partial": self.partial,
            "failed": self.failed,
            "pending": self.pending,
            "records": list(self.records),
        }
