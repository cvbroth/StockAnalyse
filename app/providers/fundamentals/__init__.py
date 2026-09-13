"""可替换的基本面数据提供者协议。"""

from .base import FundamentalDataProvider
from .akshare_ths import (
    AkshareThsFundamentalProvider,
    conservative_publication_date,
    normalize_akshare_ths_financials,
)

__all__ = [
    "AkshareThsFundamentalProvider",
    "FundamentalDataProvider",
    "conservative_publication_date",
    "normalize_akshare_ths_financials",
]
