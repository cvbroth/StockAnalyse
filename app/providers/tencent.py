"""AKShare 腾讯 A 股前复权日线适配器。"""

from __future__ import annotations

import time
from typing import Any, Iterable

import pandas as pd

from .base import MarketDataProvider, PROVIDER_DESCRIPTORS


SOURCE_NAME = "akshare_tencent_qfq"


class TencentProvider(MarketDataProvider):
    descriptor = PROVIDER_DESCRIPTORS["tx"]

    def supports_code(self, code: str) -> bool:
        return supports_code(code)

    def fetch_security_history(
        self,
        code: str,
        start_date: str,
        end_date: str,
        retries: int,
        timeout: float,
    ) -> pd.DataFrame:
        return fetch_qfq_history(code, start_date, end_date, retries, timeout)


def supports_code(code: str) -> bool:
    normalized = str(code).zfill(6)
    return normalized.startswith(("0", "3", "6"))


def to_tx_symbol(code: str) -> str:
    normalized = str(code).zfill(6)
    if normalized.startswith("6"):
        return f"sh{normalized}"
    if normalized.startswith(("0", "3")):
        return f"sz{normalized}"
    if normalized.startswith(("4", "8", "9")):
        raise ValueError(f"腾讯历史行情当前不支持北交所股票：{code}")
    raise ValueError(f"无法识别股票市场：{code}")


def find_column(frame: pd.DataFrame, candidates: Iterable[str]) -> Any | None:
    normalized = {
        str(column).strip().lower(): column for column in frame.columns
    }
    for candidate in candidates:
        if candidate.lower() in normalized:
            return normalized[candidate.lower()]
    return None


def normalize_tx_qfq(frame: pd.DataFrame, code: str) -> pd.DataFrame:
    if frame is None or frame.empty:
        raise ValueError(f"{code} 腾讯前复权行情为空")

    aliases = {
        "trade_date": ("date", "日期"),
        "open": ("open", "开盘"),
        "high": ("high", "最高"),
        "low": ("low", "最低"),
        "close": ("close", "收盘"),
        # 腾讯接口把成交量（手）命名为 amount。
        "volume": ("volume", "amount", "成交量"),
    }
    rename: dict[Any, str] = {}
    for target, candidates in aliases.items():
        source = find_column(frame, candidates)
        if source is None:
            raise ValueError(
                f"{code} 腾讯行情缺少 {target!r} 字段：{list(frame.columns)!r}"
            )
        rename[source] = target

    result = frame.rename(columns=rename)[list(aliases)].copy()
    result["trade_date"] = pd.to_datetime(
        result["trade_date"], errors="coerce"
    ).dt.strftime("%Y%m%d")
    for column in ("open", "high", "low", "close", "volume"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result = result.dropna(subset=list(aliases))
    result = result[(result["close"] > 0) & (result["volume"] >= 0)]
    result = result.sort_values("trade_date").drop_duplicates(
        "trade_date", keep="last"
    )
    if result.empty:
        raise ValueError(f"{code} 腾讯前复权行情清洗后为空")

    result["code"] = str(code).zfill(6)
    result["amount"] = float("nan")
    # 数据已经由腾讯前复权，因子设为 1 后可复用统一分析入口。
    result["adj_factor"] = 1.0
    result["source"] = SOURCE_NAME
    return result[
        [
            "code",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "adj_factor",
            "source",
        ]
    ].reset_index(drop=True)


def fetch_qfq_history(
    code: str,
    start_date: str,
    end_date: str,
    retries: int,
    timeout: float,
) -> pd.DataFrame:
    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError(
            "缺少 akshare，请执行：python -m pip install --upgrade akshare"
        ) from exc

    symbol = to_tx_symbol(code)
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            raw = ak.stock_zh_a_hist_tx(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
                timeout=timeout,
            )
            return normalize_tx_qfq(raw, code)
        except Exception as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(min(10.0, 0.8 * attempt))
    raise RuntimeError(f"{code} 腾讯前复权获取失败（已重试 {retries} 次）：{last_error}")
