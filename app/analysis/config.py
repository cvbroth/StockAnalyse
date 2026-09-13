"""版本化分析配置读取与校验。"""

from __future__ import annotations

import tomllib
import hashlib
import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from .layer2.models import Layer2Config, Layer2Thresholds, Layer2Weights
from .models import ScreenConfig


PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_LAYER1_CONFIG_PATH = PROJECT_DIR / "config" / "analysis" / "layer1.toml"
DEFAULT_LAYER2_CONFIG_PATH = PROJECT_DIR / "config" / "analysis" / "layer2.toml"


@dataclass(frozen=True)
class LoadedLayer1Config:
    version: str
    path: Path
    screen: ScreenConfig


@dataclass(frozen=True)
class LoadedLayer2Config:
    version: str
    path: Path
    quality: Layer2Config


def _read_toml(path: Path, label: str) -> tuple[Path, dict[str, Any]]:
    config_path = path.expanduser().resolve()
    if not config_path.is_file():
        raise RuntimeError(f"{label}配置不存在：{config_path}")
    try:
        with config_path.open("rb") as handle:
            payload = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeError(f"{label}配置读取失败：{config_path}：{exc}") from exc
    return config_path, payload


def _require_version(payload: dict[str, Any], label: str) -> str:
    version = payload.get("version")
    if not isinstance(version, str) or not version.strip():
        raise RuntimeError(f"{label}配置必须提供非空 version")
    return version.strip()


def _build_complete_dataclass(
    model: type[Any],
    values: Any,
    label: str,
) -> Any:
    if not isinstance(values, dict):
        raise RuntimeError(f"{label}必须是TOML区段")
    allowed = {field.name for field in fields(model)}
    unknown = sorted(set(values).difference(allowed))
    missing = sorted(allowed.difference(values))
    if unknown:
        raise RuntimeError(f"{label}包含未知参数：{', '.join(unknown)}")
    if missing:
        raise RuntimeError(f"{label}缺少参数：{', '.join(missing)}")
    try:
        return model(**dict(values))
    except TypeError as exc:
        raise RuntimeError(f"{label}无效：{exc}") from exc


def validate_screen_config(config: ScreenConfig) -> None:
    if config.min_history_days < 80:
        raise ValueError("min_history_days 至少为 80")
    if config.structure_window < 1 or config.volume_window < 1:
        raise ValueError("structure_window 和 volume_window 必须至少为 1")
    if config.breakout_lookback < 1 or config.breakout_search_days < 1:
        raise ValueError("突破回看与搜索窗口必须至少为 1")
    if config.up_down_volume_ratio <= 0 or config.breakout_volume_multiple <= 0:
        raise ValueError("成交量比例参数必须大于 0")
    if not 0 <= config.breakout_max_fall < 1:
        raise ValueError("breakout_max_fall 必须位于 [0, 1) 区间")
    if not 0 < config.market_percentile_cutoff <= 1:
        raise ValueError("market_percentile_cutoff 必须位于 (0, 1] 区间")
    if config.max_stale_calendar_days < 0:
        raise ValueError("max_stale_calendar_days 不能为负数")
    if config.min_average_volume_lots < 0:
        raise ValueError("min_average_volume_lots 不能为负数")


def load_layer1_config(path: Path | None = None) -> LoadedLayer1Config:
    config_path, payload = _read_toml(
        path or DEFAULT_LAYER1_CONFIG_PATH,
        "第一层分析",
    )
    version = _require_version(payload, "第一层分析")
    values = payload.get("screen")
    if not isinstance(values, dict):
        raise RuntimeError("第一层分析配置必须提供 [screen] 区段")

    allowed = {field.name for field in fields(ScreenConfig)}
    unknown = sorted(set(values).difference(allowed))
    missing = sorted(allowed.difference(values))
    if unknown:
        raise RuntimeError(f"第一层分析配置包含未知参数：{', '.join(unknown)}")
    if missing:
        raise RuntimeError(f"第一层分析配置缺少参数：{', '.join(missing)}")
    try:
        screen = ScreenConfig(**dict(values))
        validate_screen_config(screen)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"第一层分析配置无效：{exc}") from exc
    return LoadedLayer1Config(
        version=version,
        path=config_path,
        screen=screen,
    )


def apply_screen_overrides(
    configured: ScreenConfig,
    **overrides: Any,
) -> ScreenConfig:
    values = {
        field.name: getattr(configured, field.name) for field in fields(ScreenConfig)
    }
    values.update({key: value for key, value in overrides.items() if value is not None})
    screen = ScreenConfig(**values)
    validate_screen_config(screen)
    return screen


def validate_layer2_config(config: Layer2Config) -> None:
    if config.confirmed_top_n < 1 or config.watchlist_top_n < 1:
        raise ValueError("第二层Top N数量必须至少为1")
    weights = config.weights
    if any(value < 0 for value in weights.__dict__.values()):
        raise ValueError("第二层权重不能为负数")
    if abs(weights.positive_total - 100.0) > 1e-9:
        raise ValueError(
            f"第二层正向权重之和必须为100，实际为{weights.positive_total}"
        )
    thresholds = config.thresholds
    ordered_pairs = (
        (thresholds.volume_ratio_zero, thresholds.volume_ratio_full),
        (thresholds.breakout_volume_zero, thresholds.breakout_volume_full),
        (thresholds.retest_volume_full, thresholds.retest_volume_zero),
        (
            thresholds.breakout_recency_full_days,
            thresholds.breakout_recency_zero_days,
        ),
        (thresholds.breakout_support_zero, thresholds.breakout_support_full),
        (
            thresholds.market_percentile_zero,
            thresholds.market_percentile_full,
        ),
        (thresholds.overheat_ma20_start, thresholds.overheat_ma20_full),
        (
            thresholds.overheat_breakout_start,
            thresholds.overheat_breakout_full,
        ),
    )
    if any(right <= left for left, right in ordered_pairs):
        raise ValueError("第二层配置中的上限必须大于对应下限")
    if not (
        thresholds.breakout_extension_lower_zero
        < thresholds.breakout_extension_ideal_low
        <= thresholds.breakout_extension_ideal_high
        < thresholds.breakout_extension_upper_zero
    ):
        raise ValueError("突破距离甜蜜区间配置顺序错误")


def load_layer2_config(path: Path | None = None) -> LoadedLayer2Config:
    config_path, payload = _read_toml(
        path or DEFAULT_LAYER2_CONFIG_PATH,
        "第二层评分",
    )
    version = _require_version(payload, "第二层评分")
    weights = _build_complete_dataclass(
        Layer2Weights,
        payload.get("weights"),
        "第二层[weights]",
    )
    thresholds = _build_complete_dataclass(
        Layer2Thresholds,
        payload.get("thresholds"),
        "第二层[thresholds]",
    )
    try:
        quality = Layer2Config(
            confirmed_top_n=int(payload["confirmed_top_n"]),
            watchlist_top_n=int(payload["watchlist_top_n"]),
            weights=weights,
            thresholds=thresholds,
        )
        validate_layer2_config(quality)
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"第二层评分配置无效：{exc}") from exc
    return LoadedLayer2Config(version=version, path=config_path, quality=quality)


def analysis_config_hash(
    layer1: ScreenConfig,
    layer2: Layer2Config,
) -> str:
    payload = json.dumps(
        {"layer1": asdict(layer1), "layer2": asdict(layer2)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
