#!/usr/bin/env bash
set -euo pipefail

apply=false
compose_directory="${OPENCLAW_COMPOSE_DIR:-}"
compose_service="${OPENCLAW_COMPOSE_SERVICE:-openclaw-cli}"
qq_target="${OPENCLAW_QQ_TARGET:-}"
daily_cron="0 19 * * 1-5"
weekly_cron="0 20 * * 5"
timezone="Asia/Shanghai"

usage() {
  echo "用法：bash scripts/install_report_automations.sh --compose-dir <OpenClaw目录> --qq-target <QQ目标> [--apply]"
  echo "可选：--service openclaw-cli --daily-cron '0 19 * * 1-5' --weekly-cron '0 20 * * 5' --tz Asia/Shanghai"
}

while (( $# > 0 )); do
  case "$1" in
    --apply)
      apply=true
      shift
      ;;
    --compose-dir)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      compose_directory="$2"
      shift 2
      ;;
    --service)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      compose_service="$2"
      shift 2
      ;;
    --qq-target)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      qq_target="$2"
      shift 2
      ;;
    --daily-cron)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      daily_cron="$2"
      shift 2
      ;;
    --weekly-cron)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      weekly_cron="$2"
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

echo "A股报告推送任务预览"
echo "OpenClaw Compose目录：${compose_directory:-<未设置>}"
echo "Compose服务：${compose_service}"
echo "QQ目标：${qq_target:-<未设置>}"
echo "日报：${daily_cron}（${timezone}）"
echo "周报：${weekly_cron}（${timezone}）"
echo "容器报告目录：/reports（必须只读挂载宿主机 output/reports）"

if [[ "${apply}" != true ]]; then
  echo
  echo "当前仅预览，没有创建OpenClaw任务。确认配置后追加 --apply。"
  exit 0
fi

if [[ -z "${compose_directory}" || ! -d "${compose_directory}" ]]; then
  echo "OpenClaw Compose目录不存在；请使用 --compose-dir 指定。" >&2
  exit 2
fi
if [[ -z "${qq_target}" ]]; then
  echo "创建任务必须使用 --qq-target 指定明确的QQ接收目标。" >&2
  exit 2
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "未找到docker命令。" >&2
  exit 2
fi

compose_files=("docker-compose.yml")
if [[ -f "${compose_directory}/docker-compose.override.yml" ]]; then
  compose_files+=("docker-compose.override.yml")
fi
if [[ -f "${compose_directory}/docker-compose.extra.yml" ]]; then
  compose_files+=("docker-compose.extra.yml")
fi

compose_command=(docker compose)
for compose_file in "${compose_files[@]}"; do
  if [[ ! -f "${compose_directory}/${compose_file}" ]]; then
    echo "缺少Compose文件：${compose_directory}/${compose_file}" >&2
    exit 2
  fi
  compose_command+=(-f "${compose_file}")
done

openclaw_cli() {
  (
    cd "${compose_directory}"
    "${compose_command[@]}" run -T --rm "${compose_service}" "$@"
  )
}

if ! (
  cd "${compose_directory}"
  "${compose_command[@]}" run -T --rm --entrypoint sh "${compose_service}" \
    -lc 'test -r /reports/print-latest.sh'
); then
  echo "容器无法读取 /reports/print-latest.sh。请先生成一份报告并配置只读挂载。" >&2
  exit 2
fi

automation_list="$(openclaw_cli automations list)"
for automation_name in a-share-daily-report a-share-weekly-report; do
  if [[ "${automation_list}" == *"${automation_name}"* ]]; then
    echo "已存在同名任务 ${automation_name}，本次没有创建任何任务。" >&2
    exit 2
  fi
done

openclaw_cli automations create "${daily_cron}" \
  --name "a-share-daily-report" \
  --tz "${timezone}" \
  --exact \
  --command-argv '["sh","/reports/print-latest.sh","daily"]' \
  --command-cwd "/reports" \
  --timeout-seconds 120 \
  --announce \
  --channel qqbot \
  --to "${qq_target}"

openclaw_cli automations create "${weekly_cron}" \
  --name "a-share-weekly-report" \
  --tz "${timezone}" \
  --exact \
  --command-argv '["sh","/reports/print-latest.sh","weekly"]' \
  --command-cwd "/reports" \
  --timeout-seconds 120 \
  --announce \
  --channel qqbot \
  --to "${qq_target}"

echo "日报和周报推送任务已创建。"
echo "请使用OpenClaw Automations运行记录分别检查执行状态和投递状态。"
