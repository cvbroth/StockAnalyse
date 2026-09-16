#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_directory="$(cd "${script_directory}/.." && pwd)"

if ! command -v openclaw >/dev/null 2>&1; then
  echo "未找到 openclaw。请先安装并完成模型与搜索工具配置。" >&2
  exit 2
fi

message="/a-share-fundamental"
if (( $# > 0 )); then
  message="${message} $*"
fi

openclaw_command=(
  openclaw agent exec "${message}"
  --cwd "${project_directory}"
)
if [[ -n "${A_SHARE_RESEARCH_MODEL:-}" ]]; then
  openclaw_command+=(--model "${A_SHARE_RESEARCH_MODEL}")
fi
openclaw_command+=(--timeout 0)

exec "${openclaw_command[@]}"
