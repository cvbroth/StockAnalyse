"""逐股执行研究结果导入，支持失败隔离、复用和断点续跑。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from ..analysis.fundamentals import FundamentalResearchResult
from ..services.fundamental_research import validate_research_result_record
from ..services.fundamental_sync import write_json_atomic
from .contracts import ResearchExecutionSummary, ResearchResultProvider
from .workspace import ResearchWorkspace


class ResearchOrchestrator:
    def __init__(
        self,
        workspace: ResearchWorkspace,
        metadata: dict[str, Any],
        requests: list[dict[str, Any]],
    ) -> None:
        self.workspace = workspace
        self.metadata = metadata
        self.requests = requests
        self.run_id = str(metadata["run_id"])
        self.as_of_date = str(metadata["as_of_date"])
        self.expected = {str(item["code"]).zfill(6): item for item in requests}

    def _selected_requests(
        self,
        codes: Iterable[str] | None,
    ) -> list[dict[str, Any]]:
        if codes is None:
            return list(self.requests)
        selected_codes = {str(code).zfill(6) for code in codes}
        unknown = sorted(selected_codes.difference(self.expected))
        if unknown:
            raise RuntimeError(
                f"指定股票不在当前研究任务中：{', '.join(unknown)}"
            )
        return [
            request
            for request in self.requests
            if str(request["code"]).zfill(6) in selected_codes
        ]

    def _read_result(
        self,
        path: Path,
    ) -> FundamentalResearchResult:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"研究结果读取失败：{path}：{exc}") from exc
        return validate_research_result_record(
            raw,
            self.expected,
            self.run_id,
            self.as_of_date,
        )

    def _collect_existing(
        self,
    ) -> tuple[dict[str, FundamentalResearchResult], dict[str, str]]:
        parsed: dict[str, FundamentalResearchResult] = {}
        errors: dict[str, str] = {}
        for code in self.expected:
            path = self.workspace.result_path(code)
            if not path.is_file():
                continue
            try:
                parsed[code] = self._read_result(path)
            except RuntimeError as exc:
                errors[code] = str(exc)
        return parsed, errors

    def _build_summary(
        self,
        provider_name: str,
        selected: int,
        imported: int,
        reused: int,
        results: dict[str, FundamentalResearchResult],
        errors: dict[str, str],
    ) -> ResearchExecutionSummary:
        records: list[dict[str, Any]] = []
        counts = {"complete": 0, "partial": 0, "failed": 0, "pending": 0}
        for request in self.requests:
            code = str(request["code"]).zfill(6)
            result = results.get(code)
            error = errors.get(code)
            if result is not None:
                status = result.status
            elif error:
                status = "failed"
            else:
                status = "pending"
            counts[status] += 1
            records.append(
                {
                    "code": code,
                    "name": str(request.get("name", "")),
                    "status": status,
                    "result_path": (
                        str(self.workspace.result_path(code))
                        if result is not None
                        else None
                    ),
                    "error": error,
                }
            )
        return ResearchExecutionSummary(
            run_id=self.run_id,
            provider=provider_name,
            total=len(self.requests),
            selected=selected,
            imported=imported,
            reused=reused,
            complete=counts["complete"],
            partial=counts["partial"],
            failed=counts["failed"],
            pending=counts["pending"],
            records=tuple(records),
        )

    def execute(
        self,
        provider: ResearchResultProvider,
        codes: Iterable[str] | None = None,
        resume: bool = False,
    ) -> tuple[
        ResearchExecutionSummary,
        dict[str, FundamentalResearchResult],
    ]:
        """导入指定结果；一只失败不会阻断其他股票。"""

        selected = self._selected_requests(codes)
        existing, existing_errors = self._collect_existing()
        import_errors: dict[str, str] = dict(existing_errors)
        imported = 0
        reused = 0
        for request in selected:
            code = str(request["code"]).zfill(6)
            cached = existing.get(code)
            if resume and cached is not None and cached.status == "complete":
                reused += 1
                import_errors.pop(code, None)
                continue
            try:
                raw = provider.load(request)
                if raw is None:
                    if cached is not None:
                        import_errors.pop(code, None)
                    continue
                result = validate_research_result_record(
                    raw,
                    self.expected,
                    self.run_id,
                    self.as_of_date,
                )
                self.workspace.write_result(code, result.to_record())
                existing[code] = result
                import_errors.pop(code, None)
                imported += 1
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                if cached is None:
                    import_errors[code] = str(exc)
                else:
                    import_errors.pop(code, None)

        results, stored_errors = self._collect_existing()
        errors = {**import_errors, **stored_errors}
        ordered_records = [
            results[str(item["code"]).zfill(6)].to_record()
            for item in self.requests
            if str(item["code"]).zfill(6) in results
        ]
        self.workspace.write_aggregate(self.metadata, ordered_records)
        summary = self._build_summary(
            provider.name,
            len(selected),
            imported,
            reused,
            results,
            errors,
        )
        write_json_atomic(self.workspace.summary_path, summary.to_record())
        return summary, results

    def validate_existing(
        self,
    ) -> tuple[
        ResearchExecutionSummary,
        dict[str, FundamentalResearchResult],
    ]:
        """只读校验逐股结果，不创建或修改任何文件。"""

        results, errors = self._collect_existing()
        summary = self._build_summary(
            "validate-only",
            len(self.requests),
            0,
            len(results),
            results,
            errors,
        )
        return summary, results
