"""从单个批量JSON或按股票拆分的目录读取外部研究结果。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class FilesystemResearchProvider:
    name = "filesystem"

    def __init__(self, source: Path) -> None:
        self.source = source.expanduser().resolve()
        self._batch: dict[str, dict[str, Any]] | None = None

    def _load_json(self, path: Path) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"研究结果读取失败：{path}：{exc}") from exc

    def _load_batch(self) -> dict[str, dict[str, Any]]:
        if self._batch is not None:
            return self._batch
        if not self.source.is_file():
            self._batch = {}
            return self._batch
        payload = self._load_json(self.source)
        if not isinstance(payload, dict):
            raise RuntimeError("批量研究结果必须是JSON对象")
        records = payload.get("records")
        if records is None and "code" in payload:
            records = [payload]
        if not isinstance(records, list):
            raise RuntimeError("批量研究结果必须包含 records 数组")
        batch: dict[str, dict[str, Any]] = {}
        for raw in records:
            if not isinstance(raw, dict):
                raise RuntimeError("批量研究结果的每一项必须是对象")
            code = str(raw.get("code", "")).zfill(6)
            if code in batch:
                raise RuntimeError(f"批量研究结果包含重复股票：{code}")
            batch[code] = raw
        self._batch = batch
        return batch

    def load(self, request: dict[str, Any]) -> dict[str, Any] | None:
        code = str(request["code"]).zfill(6)
        if self.source.is_dir():
            path = self.source / f"{code}.json"
            if not path.is_file():
                return None
            payload = self._load_json(path)
            if not isinstance(payload, dict):
                raise RuntimeError(f"{code} 的研究结果必须是JSON对象")
            if "record" in payload and isinstance(payload["record"], dict):
                return payload["record"]
            return payload
        return self._load_batch().get(code)
