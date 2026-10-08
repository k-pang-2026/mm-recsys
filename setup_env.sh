#!/usr/bin/env bash
# v4: clone → one command → installed common code, CLIP cache, reproducible data and checks.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT="."; PROJECT_SET=0; ROLE=""; USE_GPU=0; SCAFFOLD_ONLY=0
PREFETCH_REQUESTED=0; SKIP_DOCKER=0; SKIP_CLIP=0; SKIP_DATA=0; REFRESH_PROMPTS=0
for arg in "$@"; do
  case "$arg" in
    --role=*) ROLE="${arg#--role=}" ;;
    --gpu) USE_GPU=1 ;;
    --scaffold-only) SCAFFOLD_ONLY=1 ;;
    --skip-docker-check) SKIP_DOCKER=1 ;;
    --skip-clip) SKIP_CLIP=1 ;;
    --skip-data) SKIP_DATA=1 ;;
    --prefetch-clip) SKIP_CLIP=0; PREFETCH_REQUESTED=1 ;;
    --refresh-prompts) REFRESH_PROMPTS=1 ;;
    --help|-h) echo "bash setup_env.sh [대상경로=.] [--role=A|B|C] [--gpu] [--scaffold-only] [--skip-docker-check] [--skip-clip] [--skip-data] [--refresh-prompts]";exit 0 ;;
    -*) echo "알 수 없는 옵션: $arg";exit 1 ;;
    *) [ "$PROJECT_SET" -eq 0 ] || { echo "대상 경로는 하나만 지정하세요.";exit 1; };PROJECT="$arg";PROJECT_SET=1 ;;
  esac
done
if [ "$SCAFFOLD_ONLY" -eq 1 ] && [ "$PREFETCH_REQUESTED" -eq 1 ]; then
  echo "--scaffold-only와 --prefetch-clip은 함께 사용할 수 없습니다.";exit 1
fi
case "$ROLE" in ""|A|B|C) ;; *) echo "역할은 A/B/C입니다.";exit 1;; esac
PY=""
for candidate in python3.11 python3.12 python3.10 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys;sys.exit(0 if (3,10)<=sys.version_info[:2]<=(3,12) else 1)' 2>/dev/null; then
    PY="$candidate";break
  fi
done
[ -n "$PY" ] || { echo "Python 3.10~3.12가 필요합니다.";exit 1; }
command -v git >/dev/null 2>&1 || { echo "git이 필요합니다.";exit 1; }
for required in config.yaml src/simulator/generate.py docs/codex_quickstart.md config/team_workflow.yaml; do
  [ -f "$SCRIPT_DIR/$required" ] || { echo "저장소 전체를 clone하세요. 누락: $required";exit 1; }
done
mkdir -p "$PROJECT"
cd "$PROJECT"
PROJECT_ROOT="$(pwd -P)"
GIT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -n "$GIT_ROOT" ]; then
  [ "$(cd "$GIT_ROOT" && pwd -P)" = "$PROJECT_ROOT" ] || { echo "저장소 루트를 지정하세요: $GIT_ROOT";exit 1; }
else
  git init -q -b main
fi
# New target gets the actual committed common implementation, never source stubs.
"$PY" - "$SCRIPT_DIR" "$PROJECT_ROOT" "$REFRESH_PROMPTS" <<'PY'
import shutil,sys
from pathlib import Path
source,target=map(Path,sys.argv[1:3]);refresh=sys.argv[3]=='1'
roots=['src','tests','scripts','config','docs','dashboard','.github','.vscode','docker']
files=['setup_env.sh','config.yaml','README.md','AGENTS.md','ai_step_prompts_optimized.md',
       'requirements.txt','requirements-torch.txt','requirements-dashboard.txt','requirements-dev.txt',
       'pytest.ini','mypy.ini','.gitignore','.dockerignore','.env','docker-compose.yml']
if source!=target:
    for folder in roots:
        for path in (source/folder).rglob('*'):
            if not path.is_file() or '__pycache__' in path.parts or path.suffix=='.pyc':continue
            relative=path.relative_to(source);destination=target/relative
            if not destination.exists():
                destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,destination)
    for name in files:
        if not (target/name).exists():shutil.copyfile(source/name,target/name)
canonical=source/'ai_step_prompts_optimized.md';alias=target/'docs/ai_step_prompts.md'
if refresh or not alias.exists():shutil.copyfile(canonical,alias)
elif alias.read_bytes()!=canonical.read_bytes():print('프롬프트 사본 차이: --refresh-prompts로 갱신하세요.')
for name in ['data','models']:
    (target/name).mkdir(exist_ok=True);(target/name/'.gitkeep').touch()
PY
if [ -n "$ROLE" ]; then
  "$PY" - "$ROLE" <<'PY'
import json,sys
from pathlib import Path
Path('.team').mkdir(exist_ok=True)
Path('.team/local.json').write_text(json.dumps({'role':sys.argv[1]},indent=2))
PY
fi
if [ "$SCAFFOLD_ONLY" -eq 1 ]; then
  echo "공통 코드 복사 완료. 의존성/모델/데이터/검증은 미측정입니다."
  exit 0
fi
if [ "$USE_GPU" -eq 1 ] && [ "$(uname -s)" = "Darwin" ]; then
  echo "--gpu는 NVIDIA CUDA 환경용입니다. macOS는 기본 CPU 설치를 사용하세요.";exit 1
fi
[ -d .venv ] || "$PY" -m venv .venv
if [ -x .venv/bin/python ]; then VPY="$PROJECT_ROOT/.venv/bin/python"
elif [ -f .venv/Scripts/python.exe ]; then VPY="$PROJECT_ROOT/.venv/Scripts/python.exe"
else echo ".venv 인터프리터가 없습니다.";exit 1;fi
"$VPY" -c 'import sys;assert (3,10)<=sys.version_info[:2]<=(3,12)'
"$VPY" -m pip install --upgrade pip wheel
TORCH_INDEX="https://download.pytorch.org/whl/cpu"
[ "$USE_GPU" -eq 0 ] || TORCH_INDEX="https://download.pytorch.org/whl/cu124"
if [ "$(uname -s)" = "Darwin" ]; then
  "$VPY" -m pip install -r requirements-torch.txt
else
  "$VPY" -m pip install -r requirements-torch.txt --index-url "$TORCH_INDEX"
fi
"$VPY" -m pip install -r requirements-dev.txt
"$VPY" -m pip check
export PYTHONHASHSEED=42
# Existing task/user cache can be selected with HF_HOME; default remains project-local.
export HF_HOME="${HF_HOME:-$PROJECT_ROOT/.cache/huggingface}"
export PYTHONPATH="$PROJECT_ROOT${PYTHONPATH:+:$PYTHONPATH}"
source scripts/local_env.sh
"$VPY" -m pytest -q tests
if [ "$SKIP_DATA" -eq 0 ]; then
  "$VPY" -m src.simulator.generate
  "$VPY" scripts/validate_common.py
  "$VPY" -m src.evaluation.diagnose_data
fi
CHECK_ARGS=()
[ "$SKIP_CLIP" -eq 0 ] || CHECK_ARGS+=(--skip-clip)
[ "$SKIP_DOCKER" -eq 0 ] || CHECK_ARGS+=(--skip-docker-check)
"$VPY" scripts/check_environment.py "${CHECK_ARGS[@]}"
"$VPY" scripts/team.py status
if [ "$SKIP_DOCKER" -eq 1 ] || [ "$SKIP_CLIP" -eq 1 ] || [ "$SKIP_DATA" -eq 1 ]; then
  echo "선택한 검사 완료. 생략한 Docker/CLIP/데이터는 미측정이며 전체 환경 PASS가 아닙니다."
else
  echo "개발환경·공통 데이터·CLIP·Docker 사전 검증 완료. 최종 모델 품질은 담당 단계에서 측정합니다."
fi
echo "Codex 다음 입력: ${ROLE:-A} 다음 단계 실행"
