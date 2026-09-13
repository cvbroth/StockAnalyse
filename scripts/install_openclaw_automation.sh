#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_directory="$(cd "${script_directory}/.." && pwd)"
automation_name="a-share-layer3-daily"
cron_expression="0 18 * * 1-5"
timezone="Asia/Shanghai"
apply=false

usage() {
  echo "用法：bash scripts/install_openclaw_automation.sh [--apply] [--cron '0 18 * * 1-5'] [--tz Asia/Shanghai]"
}

while (( $# > 0 )); do
  case "$1" in
    --apply)
      apply=true
      shift
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
  echo "未找到openclaw。请先安装并完成Gateway、模型和搜索工具配置。" >&2
  exit 2
fi

if [[ -x "${project_directory}/.venv/bin/python" ]]; then
  python_command="${project_directory}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  python_command="$(command -v python3)"
else
  echo "未找到可用Python，无法安全生成command-argv。" >&2
  exit 2
fi

command_argv="$("${python_command}" -c \
  'import json,sys; print(json.dumps(["bash", sys.argv[1], "--resume"], ensure_ascii=False))' \
  "${project_directory}/scripts/daily_pipeline.sh")"

echo "任务名称：${automation_name}"
echo "执行时间：${cron_expression}（${timezone}）"
echo "项目目录：${project_directory}"
echo "执行参数：${command_argv}"

if [[ "${apply}" != true ]]; then
  echo
  echo "当前仅预览，没有创建任务。确认无误后追加 --apply。"
  exit 0
fi

automation_list="$(openclaw automations list)"
if [[ "${automation_list}" == *"${automation_name}"* ]]; then
  echo "已存在同名任务 ${automation_name}，为避免重复调度，本次未创建。" >&2
  echo "请先用 openclaw automations list/get 检查现有任务。" >&2
  exit 2
fi

openclaw automations create "${cron_expression}" \
  --name "${automation_name}" \
  --tz "${timezone}" \
  --exact \
  --command-argv "${command_argv}" \
  --command-cwd "${project_directory}" \
  --timeout-seconds 21600 \
  --no-deliver

echo "自动化任务已创建。请运行 openclaw automations list 确认。"
