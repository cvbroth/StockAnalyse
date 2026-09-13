#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_directory="$(cd "${script_directory}/.." && pwd)"

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
