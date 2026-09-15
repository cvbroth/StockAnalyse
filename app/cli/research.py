#!/usr/bin/env python3
"""准备、导入、续跑并校验Layer3逐股研究任务。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from ..analysis.history import load_latest_full_market
from ..fundamentals import (
    DEFAULT_FUNDAMENTAL_CONFIG_PATH,
    load_fundamental_settings,
)
from ..project_config import resolve_output_path
from ..research import ResearchOrchestrator, ResearchWorkspace, load_research_request
from ..research.providers import FilesystemResearchProvider
from ..research.workspace import load_research_templates
from ..services.fundamental_research import write_layer3_results


RUN_ID_PATTERN = re.compile(r"^[0-9A-Za-z._-]+$")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="管理Layer3逐股研究任务并合并结构化结果",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
典型用法：
  python -m app.cli.research
  python -m app.cli.research --resume
  python -m app.cli.research --code 603505 600519

导入外部工具生成的批量JSON或按股票命名的JSON目录：
  python -m app.cli.research --import-results /path/to/results

只读检查已经保存的逐股结果：
  python -m app.cli.research --validate-only
""",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help=(
            "全市场扫描快照编号；省略时自动选择最近一次成功的全市场运行"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="结果目录；省略时读取 config/project.json",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_FUNDAMENTAL_CONFIG_PATH,
        help="Layer3权重与阈值TOML配置路径",
    )
    parser.add_argument(
        "--code",
        nargs="+",
        default=None,
        help="只准备或导入指定股票；必须属于当前研究任务",
    )
    parser.add_argument(
        "--import-results",
        type=Path,
        default=None,
        help=(
            "外部研究结果来源；可以是批量JSON文件，"
            "也可以是包含<股票代码>.json的目录"
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="跳过已有complete结果，只处理缺失、partial或failed股票",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="只读校验已保存的逐股结果，不创建或修改文件",
    )
    parser.add_argument(
        "--exchange-dir",
        type=Path,
        default=None,
        help=(
            "隔离研究交换目录；任务写入work_items，外部工具只向inbox投递"
        ),
    )
    return parser


def _read_financial_records(
    path: Path,
    run_id: str,
    as_of_date: str,
) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"财务量化结果读取失败：{path}：{exc}") from exc
    metadata = payload.get("metadata")
    records = payload.get("records")
    if not isinstance(metadata, dict) or not isinstance(records, list):
        raise RuntimeError("财务量化结果必须包含 metadata 和 records")
    if str(metadata.get("run_id")) != run_id:
        raise RuntimeError("财务量化结果不属于当前运行编号")
    if str(metadata.get("as_of_date")) != as_of_date:
        raise RuntimeError("财务量化结果截止日期与研究请求不一致")
    return records


def _normalize_codes(values: list[str] | None) -> set[str] | None:
    if values is None:
        return None
    codes: set[str] = set()
    for value in values:
        code = str(value).zfill(6)
        if len(code) != 6 or not code.isdigit():
            raise RuntimeError(f"股票代码无效：{value}")
        codes.add(code)
    return codes


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output_dir, output_source = resolve_output_path(args.output_dir)
        run_id = args.run_id
        auto_selected = False
        if run_id is None:
            run_id, _ = load_latest_full_market(output_dir)
            if run_id is None:
                raise RuntimeError(
                    "尚无完整全市场运行。请先执行：python -m app.cli.screen --all"
                )
            auto_selected = True
        if not RUN_ID_PATTERN.fullmatch(str(run_id)):
            raise RuntimeError(f"运行编号格式无效：{run_id}")
        run_directory = output_dir / "runs" / run_id
        request_path = run_directory / "fundamental" / "research_request.json"
        template_path = (
            run_directory / "fundamental" / "research_results.template.json"
        )
        if not request_path.is_file() or not template_path.is_file():
            raise RuntimeError(
                "当前快照尚未准备研究任务。请先执行："
                f"python -m app.cli.fundamentals --run-id {run_id}"
            )
        metadata, requests = load_research_request(request_path)
        if str(metadata["run_id"]) != run_id:
            raise RuntimeError("研究请求与所选运行编号不一致")
        codes = _normalize_codes(args.code)
        workspace = ResearchWorkspace(run_directory, args.exchange_dir)
        orchestrator = ResearchOrchestrator(workspace, metadata, requests)

        if args.validate_only:
            summary, research_results = orchestrator.validate_existing()
            layer3_path = None
            source = "只读校验"
        else:
            templates = load_research_templates(template_path)
            selected_codes = codes or {
                str(item["code"]).zfill(6) for item in requests
            }
            workspace.prepare(requests, templates, selected_codes)
            import_source = (
                args.import_results.expanduser().resolve()
                if args.import_results is not None
                else workspace.inbox_directory
            )
            if args.import_results is not None and not import_source.exists():
                raise RuntimeError(f"指定的研究结果来源不存在：{import_source}")
            provider = FilesystemResearchProvider(import_source)
            summary, research_results = orchestrator.execute(
                provider,
                codes=codes,
                resume=args.resume,
            )
            settings = load_fundamental_settings(args.config)
            financial_records = _read_financial_records(
                run_directory / "fundamental" / "financial_quant.json",
                run_id,
                str(metadata["as_of_date"]),
            )
            layer3_path, _ = write_layer3_results(
                financial_records,
                requests,
                research_results,
                run_directory,
                run_id,
                str(metadata["as_of_date"]),
                settings.version,
                settings.scoring,
            )
            source = str(import_source)
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        print(f"研究任务执行失败：{exc}", file=sys.stderr)
        return 2

    selection = "自动选择最近一次" if auto_selected else "命令行指定"
    print(f"结果目录：{output_source} → {output_dir}")
    print(
        f"运行快照：{selection} → {run_id}"
        f"（数据截止 {metadata['as_of_date']}）"
    )
    print(f"研究结果来源：{source}")
    print(
        f"研究任务：总计 {summary.total}，本次选择 {summary.selected}；"
        f"导入 {summary.imported}，复用 {summary.reused}。"
    )
    print(
        f"结果状态：complete {summary.complete}，partial {summary.partial}，"
        f"failed {summary.failed}，pending {summary.pending}。"
    )
    if not args.validate_only:
        print(f"逐股任务目录：{workspace.work_items_directory}")
        print(f"外部结果投递目录：{workspace.inbox_directory}")
        print(f"汇总研究结果：{workspace.aggregate_path}")
        print(f"Layer3结果：{layer3_path}")
    if summary.has_errors:
        for record in summary.records:
            if record.get("error"):
                print(
                    f"失败：{record['code']} {record['name']}："
                    f"{record['error']}",
                    file=sys.stderr,
                )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
