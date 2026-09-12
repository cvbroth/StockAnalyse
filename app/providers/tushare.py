"""Tushare未复权日线与复权因子提供者。"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .base import MarketDataProvider, PROVIDER_DESCRIPTORS


class EndpointRateLimiter:
    """按接口独立限速，并从服务端错误自动收紧频率。"""

    def __init__(self, label: str, calls_per_minute: float) -> None:
        self.label = label
        self.calls_per_minute = calls_per_minute
        self.last_request_started: float | None = None

    @property
    def interval_seconds(self) -> float:
        if self.calls_per_minute <= 0:
            return 0.0
        base_interval = 60.0 / self.calls_per_minute
        return base_interval + min(1.0, max(0.1, base_interval * 0.02))

    def describe_limit(self) -> str:
        if 0 < self.calls_per_minute < 1:
            return f"每小时最多 {self.calls_per_minute * 60:g} 次"
        return f"每分钟最多 {self.calls_per_minute:g} 次"

    def wait_before_request(self) -> None:
        interval = self.interval_seconds
        if interval <= 0:
            self.last_request_started = time.monotonic()
            return
        now = time.monotonic()
        if self.last_request_started is not None:
            remaining = interval - (now - self.last_request_started)
            if remaining > 0:
                print(
                    f"{self.label} 频率控制：等待 {remaining:.1f} 秒"
                    f"（{self.describe_limit()}）……",
                    flush=True,
                )
                time.sleep(remaining)
        self.last_request_started = time.monotonic()

    def adapt_to_error(self, error: Exception) -> bool:
        message = str(error)
        lowered = message.lower()
        if not (
            "频率超限" in message
            or "rate limit" in lowered
            or "too many requests" in lowered
        ):
            return False
        minute_match = re.search(r"(\d+(?:\.\d+)?)\s*次\s*/\s*分钟", message)
        hour_match = re.search(r"(\d+(?:\.\d+)?)\s*次\s*/\s*小时", message)
        if minute_match:
            detected_limit = float(minute_match.group(1))
        elif hour_match:
            detected_limit = float(hour_match.group(1)) / 60.0
        else:
            detected_limit = 1.0
        if self.calls_per_minute <= 0 or detected_limit < self.calls_per_minute:
            self.calls_per_minute = detected_limit
            print(
                f"{self.label} 已识别服务端限制：{self.describe_limit()}。",
                file=sys.stderr,
                flush=True,
            )
        return True

    def estimate_seconds(self, request_count: int) -> float:
        return max(0, request_count - 1) * self.interval_seconds


def call_with_retries(
    label: str,
    operation: Callable[[], Any],
    retries: int,
    rate_limiter: EndpointRateLimiter,
) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            rate_limiter.wait_before_request()
            return operation()
        except Exception as exc:
            last_error = exc
            if attempt >= retries:
                break
            if rate_limiter.adapt_to_error(exc):
                print(
                    f"{label} 第 {attempt} 次触发限频，将按服务端频率重试。",
                    file=sys.stderr,
                    flush=True,
                )
            else:
                wait_seconds = min(20.0, 1.5 * (2 ** (attempt - 1)))
                print(
                    f"{label} 第 {attempt} 次失败，{wait_seconds:.1f} 秒后重试：{exc}",
                    file=sys.stderr,
                    flush=True,
                )
                time.sleep(wait_seconds)
    raise RuntimeError(f"{label} 获取失败（已重试 {retries} 次）：{last_error}")


def read_dotenv_value(path: Path, variable_name: str) -> str | None:
    if not path.is_file():
        return None
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError as exc:
        raise RuntimeError(f"无法读取 .env 文件 {path}: {exc}") from exc
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[7:].lstrip()
        key, separator, raw_value = stripped.partition("=")
        if not separator or key.strip() != variable_name:
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        return value.strip()
    return None


def resolve_token(token_environment: str, env_file: Path) -> tuple[str, str]:
    token = os.environ.get(token_environment, "").strip()
    if token:
        return token, f"环境变量 {token_environment}"
    resolved_env_file = env_file.expanduser().resolve()
    token = (read_dotenv_value(resolved_env_file, token_environment) or "").strip()
    if token:
        return token, str(resolved_env_file)
    raise RuntimeError(
        f"未找到 {token_environment}。已经检查：\n"
        f"1. 当前进程环境变量 {token_environment}\n"
        f"2. 配置文件 {resolved_env_file}\n"
        "Linux/macOS 可执行：export TUSHARE_TOKEN='你的Token'\n"
        "Windows PowerShell 可执行：$env:TUSHARE_TOKEN='你的Token'\n"
        f"也可以在 {resolved_env_file} 中写入：\n"
        f"{token_environment}=你的Token"
    )


def normalize_trade_date(
    daily: pd.DataFrame,
    factors: pd.DataFrame,
    trade_date: str,
    minimum_rows: int,
) -> pd.DataFrame:
    daily_required = {
        "ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"
    }
    factor_required = {"ts_code", "trade_date", "adj_factor"}
    if daily is None or daily.empty:
        raise ValueError(f"{trade_date} 日线行情为空，数据可能尚未更新")
    if factors is None or factors.empty:
        raise ValueError(f"{trade_date} 复权因子为空，请检查Tushare接口权限")
    missing_daily = daily_required.difference(daily.columns)
    missing_factors = factor_required.difference(factors.columns)
    if missing_daily:
        raise ValueError(f"日线行情缺少字段：{sorted(missing_daily)}")
    if missing_factors:
        raise ValueError(f"复权因子缺少字段：{sorted(missing_factors)}")
    if len(daily) < minimum_rows:
        raise ValueError(
            f"{trade_date} 日线仅返回 {len(daily)} 行，低于安全门槛 {minimum_rows}"
        )

    price = daily[list(daily_required)].copy()
    factor = factors[list(factor_required)].copy()
    price["ts_code"] = price["ts_code"].astype(str).str.upper()
    factor["ts_code"] = factor["ts_code"].astype(str).str.upper()
    price["trade_date"] = price["trade_date"].astype(str)
    factor["trade_date"] = factor["trade_date"].astype(str)
    factor = factor.drop_duplicates(["ts_code", "trade_date"], keep="last")
    merged = price.merge(
        factor,
        on=["ts_code", "trade_date"],
        how="left",
        validate="one_to_one",
    )
    coverage = float(merged["adj_factor"].notna().mean())
    if coverage < 0.98:
        raise ValueError(f"{trade_date} 复权因子覆盖率仅 {coverage:.2%}，拒绝写入")
    merged = merged.dropna(subset=["adj_factor"]).copy()
    merged["code"] = merged["ts_code"].astype(str).str.split(".").str[0].str.zfill(6)
    merged = merged.rename(columns={"vol": "volume"})
    numeric_columns = (
        "open", "high", "low", "close", "volume", "amount", "adj_factor"
    )
    for column in numeric_columns:
        merged[column] = pd.to_numeric(merged[column], errors="coerce")
    merged = merged.dropna(
        subset=["open", "high", "low", "close", "volume", "adj_factor"]
    )
    merged = merged[
        (merged["close"] > 0)
        & (merged["volume"] >= 0)
        & (merged["adj_factor"] > 0)
    ]
    merged["source"] = "tushare"
    return merged[
        [
            "code", "trade_date", "open", "high", "low", "close",
            "volume", "amount", "adj_factor", "source",
        ]
    ].drop_duplicates(["code", "trade_date"], keep="last")


class TushareProvider(MarketDataProvider):
    descriptor = PROVIDER_DESCRIPTORS["tushare"]

    def __init__(
        self,
        token_environment: str,
        env_file: Path,
        retries: int,
        pause: float,
        minimum_rows: int,
        daily_per_minute: float,
        factor_per_minute: float,
    ) -> None:
        token, source = resolve_token(token_environment, env_file)
        try:
            import tushare as ts
        except ImportError as exc:
            raise RuntimeError(
                "缺少 tushare，请执行：python -m pip install --upgrade tushare"
            ) from exc
        print(f"Tushare Token 已从 {source} 读取。", flush=True)
        self.client = ts.pro_api(token)
        self.retries = retries
        self.pause = pause
        self.minimum_rows = minimum_rows
        self.daily_rate_limiter = EndpointRateLimiter(
            "daily 接口", daily_per_minute
        )
        self.factor_rate_limiter = EndpointRateLimiter(
            "adj_factor 接口", factor_per_minute
        )

    def estimate_seconds(self, request_count: int) -> float:
        return self.factor_rate_limiter.estimate_seconds(request_count)

    def fetch_trade_date(self, trade_date: str) -> tuple[pd.DataFrame, int, int]:
        daily = call_with_retries(
            f"{trade_date} 全市场日线",
            lambda: self.client.daily(trade_date=trade_date),
            self.retries,
            self.daily_rate_limiter,
        )
        if self.pause > 0:
            time.sleep(self.pause)
        factors = call_with_retries(
            f"{trade_date} 全市场复权因子",
            lambda: self.client.adj_factor(trade_date=trade_date),
            self.retries,
            self.factor_rate_limiter,
        )
        if self.pause > 0:
            time.sleep(self.pause)
        normalized = normalize_trade_date(
            daily, factors, trade_date, self.minimum_rows
        )
        return normalized, len(daily), len(factors)
