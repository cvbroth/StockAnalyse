#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_directory="$(cd "${script_directory}/.." && pwd)"
state_file="${A_SHARE_PIPELINE_STATE_FILE:-${project_directory}/output/pipeline_state.json}"

if [[ -n "${PIPELINE_PYTHON:-}" ]]; then
  python_command="${PIPELINE_PYTHON}"
elif [[ -x "${project_directory}/.venv/bin/python" ]]; then
  python_command="${project_directory}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  python_command="$(command -v python3)"
else
  echo "未找到Python。" >&2
  exit 2
fi

if [[ ! -r "${state_file}" ]]; then
  echo "尚无流水线状态：${state_file}"
  exit 0
fi

"${python_command}" - "${state_file}" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
print(f"状态：{payload.get('status', 'unknown')}")
print(f"运行编号：{payload.get('run_id') or '尚未生成'}")
print(f"更新时间：{payload.get('updated_at') or '未知'}")
for name, stage in (payload.get("stages") or {}).items():
    status = stage.get("status", "unknown")
    return_code = stage.get("return_code")
    suffix = "" if return_code is None else f"，退出码 {return_code}"
    print(f"- {name}: {status}{suffix}")
PY
