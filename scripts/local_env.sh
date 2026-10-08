# 사용법: source scripts/local_env.sh   (테스트/warmup/streamlit 등 로컬 실행 전)
export REDIS_HOST=localhost
export REDIS_PORT=6379
export API_URL=http://localhost:8000
export CONFIG_PATH=config.yaml
export HF_HOME="${HF_HOME:-$PWD/.cache/huggingface}"
export PYTHONHASHSEED=42
# SCALE은 호출자가 지정하면 유지, 없으면 dev. .env를 source하면 Docker host로 되돌아간다.
export SCALE="${SCALE:-dev}"
echo "[local_env] REDIS_HOST=$REDIS_HOST API_URL=$API_URL"
