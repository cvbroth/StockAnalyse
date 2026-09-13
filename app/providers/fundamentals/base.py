"""基本面数据提供者协议。"""

from __future__ import annotations

from typing import Protocol

from ...fundamentals import FundamentalDataset, FundamentalFetchRequest


class FundamentalDataProvider(Protocol):
    provider_id: str

    def fetch(self, request: FundamentalFetchRequest) -> FundamentalDataset:
        """取得不晚于 request.as_of_date 的标准化基本面数据。"""

        ...
