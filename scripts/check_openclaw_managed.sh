#!/usr/bin/env bash
set -euo pipefail

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_directory="$(cd "${script_directory}/.." && pwd)"
python_command="${PIPELINE_PYTHON:-/opt/stockanalyse-venv/bin/python}"
smoke_agent=false

usage() {
  echo "用法：bash scripts/check_openclaw_managed.sh [--python PATH] [--smoke-agent]"
}

while (( $# > 0 )); do
  case "$1" in
    --python)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      python_command="$2"
      shift 2
      ;;
    --smoke-agent)
      smoke_agent=true
      shift
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

failures=0
pass() { echo "[通过] $*"; }
fail() { echo "[失败] $*" >&2; failures=$((failures + 1)); }
warn() { echo "[提醒] $*" >&2; }

[[ -r "${project_directory}/app/cli/pipeline.py" ]] \
  && pass "项目代码可读：${project_directory}" \
  || fail "项目代码不可读：${project_directory}"
[[ -w "${project_directory}/data" ]] \
  && pass "data目录可写" \
  || fail "data目录不可写"
[[ -w "${project_directory}/output" ]] \
  && pass "output目录可写" \
  || fail "output目录不可写"

if [[ -x "${python_command}" ]]; then
  pass "项目Python可执行：${python_command}"
  if "${python_command}" -c 'import sys; assert sys.version_info >= (3, 11); import akshare, pandas, tushare' >/dev/null 2>&1; then
    pass "Python版本和项目依赖符合要求"
  else
    fail "Python低于3.11或项目依赖导入失败；请重新构建Managed镜像"
  fi
else
  fail "项目Python不存在或不可执行：${python_command}"
fi

if command -v openclaw >/dev/null 2>&1; then
  pass "OpenClaw命令可用：$(command -v openclaw)"
  if openclaw agent exec --help >/dev/null 2>&1; then
    pass "openclaw agent exec可用"
  else
    fail "openclaw agent exec不可用"
  fi
  if openclaw models list --json >/dev/null 2>&1; then
    pass "OpenClaw模型配置可读取"
  else
    fail "无法读取OpenClaw模型配置"
  fi
else
  fail "容器PATH中没有openclaw"
fi

if [[ -S /var/run/docker.sock ]]; then
  warn "检测到Docker Socket；Managed模式不需要它，建议移除挂载。"
else
  pass "未挂载Docker Socket"
fi

if [[ "${smoke_agent}" == true && ${failures} -eq 0 ]]; then
  smoke_command=(
    openclaw agent exec
    "Reply with exactly: STOCKANALYSE_MANAGED_OK"
    --cwd "${project_directory}"
  )
  if [[ -n "${A_SHARE_RESEARCH_MODEL:-}" ]]; then
    smoke_command+=(--model "${A_SHARE_RESEARCH_MODEL}")
  fi
  smoke_command+=(--timeout 120)
  echo "[检查] 正在执行一次会产生模型调用的Agent冒烟测试……"
  if "${smoke_command[@]}"; then
    pass "Agent冒烟测试完成"
  else
    fail "Agent冒烟测试失败"
  fi
fi

if (( failures > 0 )); then
  echo "Managed模式预检失败：${failures}项。" >&2
  exit 2
fi

echo "Managed模式基础预检通过。"
