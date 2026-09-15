#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_directory="$(cd "${script_directory}/.." && pwd)"
lock_file="${A_SHARE_PIPELINE_LOCK_FILE:-${project_directory}/output/.daily_pipeline.lock}"

mkdir -p "$(dirname "${lock_file}")"
if command -v flock >/dev/null 2>&1; then
  exec {pipeline_lock_fd}>"${lock_file}"
  if ! flock --nonblock "${pipeline_lock_fd}"; then
    echo "已有一条每日流水线正在运行；本次为防止重复写入而退出。" >&2
    exit 75
  fi
else
  echo "警告：系统没有flock，无法启用重复运行保护。" >&2
fi

if [[ -x "${project_directory}/.venv/bin/python" ]]; then
  python_command="${project_directory}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  python_command="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  python_command="$(command -v python)"
else
  echo "未找到Python。请先创建项目虚拟环境并安装依赖。" >&2
  exit 2
fi

cd "${project_directory}"
exec "${python_command}" -m app.cli.pipeline "$@"
