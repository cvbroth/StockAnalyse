"""行情数据提供者的公共契约与能力描述。"""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderDescriptor:
    provider_id: str
    label: str
    market_scope: str
    adjustment_mode: str
    update_unit: str
    requires_token: bool


class MarketDataProvider(ABC):
    """所有行情提供者共享的身份与能力接口。"""

    descriptor: ProviderDescriptor

    @property
    def provider_id(self) -> str:
        return self.descriptor.provider_id

    @property
    def label(self) -> str:
        return self.descriptor.label


PROVIDER_DESCRIPTORS = {
    "tx": ProviderDescriptor(
        provider_id="tx",
        label="腾讯前复权",
        market_scope="沪深",
        adjustment_mode="provider_qfq",
        update_unit="security",
        requires_token=False,
    ),
    "tushare": ProviderDescriptor(
        provider_id="tushare",
        label="Tushare未复权日线+复权因子",
        market_scope="沪深京",
        adjustment_mode="raw_plus_factor",
        update_unit="trade_date",
        requires_token=True,
    ),
}


def get_provider_descriptor(provider_id: str) -> ProviderDescriptor:
    try:
        return PROVIDER_DESCRIPTORS[provider_id]
    except KeyError as exc:
        raise ValueError(f"不支持的数据源：{provider_id}") from exc
