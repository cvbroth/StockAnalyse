"""未配置基本面提供者时的安全默认实现。"""

from __future__ import annotations

from .contracts import FundamentalInput, FundamentalResult


class DisabledFundamentalAnalyzer:
    name = "disabled"

    def analyze(self, stock: FundamentalInput) -> FundamentalResult:
        return FundamentalResult(
            status="disabled",
            provider=self.name,
            scores={},
            vetoes=(),
            evidence=(),
            note="基本面分析尚未启用；技术分不会冒充基本面结论",
        )
