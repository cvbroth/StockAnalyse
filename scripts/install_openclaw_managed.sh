#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_directory="$(cd "${script_directory}/.." && pwd)"
automation_name="a-share-daily-pipeline"
cron_expression="1 18 * * 1-5"
timezone="Asia/Shanghai"
pipeline_python="${PIPELINE_PYTHON:-/opt/stockanalyse-venv/bin/python}"
research_model="${A_SHARE_RESEARCH_MODEL:-}"
qq_target=""
include_weekly=true
apply=false

usage() {
  echo "用法：bash scripts/install_openclaw_managed.sh [--apply] [--python PATH] [--research-model ID] [--qq-target TARGET] [--no-weekly]"
  echo "可选：--name NAME --cron '1 18 * * 1-5' --tz Asia/Shanghai"
}

while (( $# > 0 )); do
  case "$1" in
    --apply)
      apply=true
      shift
      ;;
    --python)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      pipeline_python="$2"
      shift 2
      ;;
    --research-model)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      research_model="$2"
      shift 2
      ;;
    --qq-target)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      qq_target="$2"
      shift 2
      ;;
    --no-weekly)
      include_weekly=false
      shift
      ;;
    --name)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      automation_name="$2"
      shift 2
      ;;
    --cron)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      cron_expression="$2"
      shift 2
      ;;
    --tz)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      timezone="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "未知参数：$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if ! command -v openclaw >/dev/null 2>&1; then
  echo "未找到openclaw；请在OpenClaw Gateway容器内运行本脚本。" >&2
  exit 2
fi
if [[ ! -x "${pipeline_python}" ]]; then
  echo "容器内Python不存在或不可执行：${pipeline_python}" >&2
  exit 2
fi

command_argv="$("${pipeline_python}" -c \
  'import json,sys; print(json.dumps(["bash", sys.argv[1], "--resume"], ensure_ascii=False))' \
  "${project_directory}/scripts/run_managed_daily.sh")"

echo "部署模式：OpenClaw Managed"
echo "任务名称：${automation_name}"
echo "执行时间：${cron_expression}（${timezone}）"
echo "项目目录：${project_directory}"
echo "容器Python：${pipeline_python}"
echo "研究执行器：local-openclaw"
echo "研究模型：${research_model:-继承OpenClaw默认模型}"
echo "QQ投递：${qq_target:-关闭；仅保留运行记录和报告文件}"
echo "周五随任务完成推送周报：${include_weekly}"
echo "执行参数：${command_argv}"

if [[ "${apply}" != true ]]; then
  echo
  echo "当前仅预览，没有修改Automation。确认无误后追加 --apply。"
  exit 0
fi

include_weekly_value=1
if [[ "${include_weekly}" != true ]]; then
  include_weekly_value=0
fi
environment_arguments=(
  --command-env "PIPELINE_PYTHON=${pipeline_python}"
  --command-env "A_SHARE_RESEARCH_EXECUTOR=local-openclaw"
  --command-env "A_SHARE_MANAGED_INCLUDE_WEEKLY=${include_weekly_value}"
  --command-env "A_SHARE_RESEARCH_MODEL=${research_model}"
)

delivery_arguments=(--no-deliver)
if [[ -n "${qq_target}" ]]; then
  delivery_arguments=(--announce --channel qqbot --to "${qq_target}")
fi

automation_json="$(openclaw automations list --all --json)"
existing_id="$(printf '%s' "${automation_json}" | "${pipeline_python}" -c '
import json, sys
name = sys.argv[1]
payload = json.load(sys.stdin)
def objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)
for row in objects(payload):
    if row.get("name") == name and (row.get("id") or row.get("jobId")):
        print(row.get("id") or row.get("jobId"))
        break
' "${automation_name}")"

common_arguments=(
  --tz "${timezone}"
  --exact
  --command-argv "${command_argv}"
  --command-cwd "${project_directory}"
  "${environment_arguments[@]}"
  --timeout-seconds 21600
  --output-max-bytes 65536
  "${delivery_arguments[@]}"
)

if [[ -n "${existing_id}" ]]; then
  openclaw automations edit "${existing_id}" \
    --cron "${cron_expression}" \
    "${common_arguments[@]}"
  echo "已更新现有Automation：${automation_name}（${existing_id}）。"
else
  openclaw automations create "${cron_expression}" \
    --name "${automation_name}" \
    "${common_arguments[@]}"
  echo "已创建Automation：${automation_name}。"
fi

echo "请用 openclaw automations list 和 runs 检查定义、执行与投递状态。"
