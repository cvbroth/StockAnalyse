#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_directory="$(cd "${script_directory}/.." && pwd)"
log_directory="${A_SHARE_PIPELINE_LOG_DIR:-${project_directory}/output/logs}"
timestamp="$(date +%Y%m%d-%H%M%S)"
log_file="${log_directory}/managed-daily-${timestamp}.log"

mkdir -p "${log_directory}"

pipeline_arguments=("$@")
if (( ${#pipeline_arguments[@]} == 0 )); then
  pipeline_arguments=(--resume)
fi

set +e
bash "${script_directory}/daily_pipeline.sh" "${pipeline_arguments[@]}" \
  >"${log_file}" 2>&1
return_code=$?
set -e

if (( return_code != 0 )); then
  echo "A股每日流水线失败（退出码 ${return_code}）。" >&2
  echo "最后40行日志：" >&2
  tail -n 40 "${log_file}" >&2 || true
  exit "${return_code}"
fi

print_script="${project_directory}/output/reports/print-latest.sh"
if [[ ! -r "${print_script}" ]]; then
  echo "流水线已完成，但没有生成报告发布脚本：${print_script}" >&2
  exit 2
fi

report_directory="${project_directory}/output/reports"
daily_message="$(A_SHARE_REPORT_DIR="${report_directory}" sh "${print_script}" daily)"
weekly_message="NO_REPLY"
if [[ "${A_SHARE_MANAGED_INCLUDE_WEEKLY:-1}" != "0" && "$(date +%u)" == "5" ]]; then
  weekly_message="$(A_SHARE_REPORT_DIR="${report_directory}" sh "${print_script}" weekly)"
fi

if [[ "${daily_message}" == "NO_REPLY" && "${weekly_message}" == "NO_REPLY" ]]; then
  echo "NO_REPLY"
  exit 0
fi
if [[ "${daily_message}" != "NO_REPLY" ]]; then
  printf '%s\n' "${daily_message}"
fi
if [[ "${weekly_message}" != "NO_REPLY" ]]; then
  if [[ "${daily_message}" != "NO_REPLY" ]]; then
    printf '\n—— 本周汇总 ——\n'
  fi
  printf '%s\n' "${weekly_message}"
fi
