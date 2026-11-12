#!/bin/bash
# macOS: double-click in Finder (or run ./run_bridge.command). First run creates .venv and installs deps.
cd "$(dirname "$0")" || exit 1
SCRIPT="${SCRIPT:-spacemouse_bridge.py}"
if [ ! -x .venv/bin/python ]; then
  if ! command -v python3 >/dev/null 2>&1; then
    echo "需要 Python 3.9+: https://www.python.org/downloads/macos/"
    read -r -p "按回车退出" _; exit 1
  fi
  echo "首次运行: 创建 .venv 并安装依赖..."
  python3 -m venv .venv && .venv/bin/python -m pip install -q --upgrade pip \
    && .venv/bin/python -m pip install -q -r requirements.txt || {
      rm -rf .venv; echo "依赖安装失败"; read -r -p "按回车退出" _; exit 1; }
fi
exec .venv/bin/python "$SCRIPT" "$@"
