#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_directory="$(cd "${script_directory}/.." && pwd)"
apply=false
on_calendar="Mon..Fri *-*-* 18:00:00 Asia/Shanghai"
timeout_seconds=21600
unit_name="a-share-daily-pipeline"

usage() {
  echo "用法：bash scripts/install_host_pipeline_timer.sh [--apply] [--calendar '<systemd OnCalendar>'] [--timeout-seconds N]"
}

while (( $# > 0 )); do
  case "$1" in
    --apply)
      apply=true
      shift
      ;;
    --calendar)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      on_calendar="$2"
      shift 2
      ;;
    --timeout-seconds)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      timeout_seconds="$2"
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

if [[ ! "${timeout_seconds}" =~ ^[1-9][0-9]*$ ]]; then
  echo "--timeout-seconds 必须是正整数。" >&2
  exit 2
fi

service_content="[Unit]
Description=A-share daily analysis and report pipeline

[Service]
Type=oneshot
WorkingDirectory=\"${project_directory}\"
ExecStart=/usr/bin/env bash \"${project_directory}/scripts/daily_pipeline.sh\" --resume
TimeoutStartSec=${timeout_seconds}
"

timer_content="[Unit]
Description=Run A-share daily pipeline on trading weekdays

[Timer]
OnCalendar=${on_calendar}
Persistent=true
RandomizedDelaySec=0
Unit=${unit_name}.service

[Install]
WantedBy=timers.target
"

echo "A股宿主机每日流水线定时任务预览"
echo "项目目录：${project_directory}"
echo "计划时间：${on_calendar}"
echo "最长运行：${timeout_seconds}秒"
echo
echo "--- ${unit_name}.service ---"
printf '%s\n' "${service_content}"
echo "--- ${unit_name}.timer ---"
printf '%s\n' "${timer_content}"

if [[ "${apply}" != true ]]; then
  echo "当前仅预览，没有写入systemd。确认后追加 --apply。"
  exit 0
fi

if ! command -v systemctl >/dev/null 2>&1; then
  echo "当前系统没有systemctl，无法安装systemd用户定时器。" >&2
  exit 2
fi

user_unit_directory="${XDG_CONFIG_HOME:-${HOME}/.config}/systemd/user"
mkdir -p "${user_unit_directory}"
printf '%s\n' "${service_content}" > "${user_unit_directory}/${unit_name}.service"
printf '%s\n' "${timer_content}" > "${user_unit_directory}/${unit_name}.timer"

systemctl --user daemon-reload
systemctl --user enable --now "${unit_name}.timer"

echo "宿主机每日流水线定时器已启用。"
systemctl --user list-timers "${unit_name}.timer" --no-pager
