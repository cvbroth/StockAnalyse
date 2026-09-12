"""可替换的行情数据源适配器。"""
"""可替换行情数据提供者。"""

from .base import MarketDataProvider, ProviderDescriptor, get_provider_descriptor
from .tencent import TencentProvider
from .tushare import TushareProvider

__all__ = [
    "MarketDataProvider",
    "ProviderDescriptor",
    "TencentProvider",
    "TushareProvider",
    "get_provider_descriptor",
]
