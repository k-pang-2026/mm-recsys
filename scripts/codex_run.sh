#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -x .venv/bin/python ]; then VPY=.venv/bin/python
elif [ -f .venv/Scripts/python.exe ]; then VPY=.venv/Scripts/python.exe
else echo "먼저 Codex에 '개발환경 준비'를 지시하거나 bash setup_env.sh . --role=${1:-A}를 실행하세요.";exit 1;fi
source scripts/local_env.sh
exec "$VPY" scripts/team.py run "${1:?역할 A/B/C 필요}"
