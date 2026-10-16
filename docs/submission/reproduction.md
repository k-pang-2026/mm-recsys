# 실행과 재현

저장소: https://github.com/k-pang-2026/mm-recsys

## 새 클론

Python 3.10–3.12, Git, Docker Engine/Desktop와 Compose v2가 필요하다.
권장 RAM 16GB·CPU 4코어·여유 디스크 50GB·Docker 메모리 8GB 이상이다.
첫 CLIP 다운로드에는 Hugging Face 접근이 필요하고 이후 추론은 로컬에서 수행한다.

```bash
git clone https://github.com/k-pang-2026/mm-recsys.git
cd mm-recsys
docker compose up --build
```

이 명령은 foreground로 네 서비스를 시작한다. 터미널을 반환받으려면 `-d`를 붙인다.
`docker-compose`는 별도 설치된 CLI의 이름이며 위 명령은 Compose v2를 기준으로 한다.
API 단일 writer가 데이터·CLIP 임베딩·인덱스·추천 모델·Redis 프로필을 준비한다.
검색/추천 모델이 준비될 때까지 `/health`는 200, `/ready`와 모델 API는 503이다.
기본 준비 제한은 21,600초다. 최초 다운로드/전체 생성 시간은 미측정이며
B10의 기존 데이터·검색 캐시 재사용 시간과 혼동하지 않는다.

```bash
docker compose logs -f api-server
curl --fail http://localhost:8000/ready
curl --fail -X POST http://localhost:8000/api/search \
  -H 'Content-Type: application/json' \
  -d '{"query_text":"black shirt","top_k":10}'
curl --fail 'http://localhost:8000/api/recommend?user_id=U000001&top_n=10'
docker compose exec api-server python scripts/smoke_test.py --benchmark
```

API 문서는 http://localhost:8000/docs, Streamlit은 http://localhost:8501,
Redis는 localhost:6379다. 검색 응답의 `total_count`는 가용 전체 카탈로그 수다.
검색은 JSON/base64 및 multipart 이미지 업로드를 지원하고 빈 입력은 422다.
미등록 사용자 추천도 cold-start 경로로 응답한다. 기본값·포트·full 별도 프로젝트·
선택 CT profile·메모리/스레드 설정은 [README](../../README.md)의 Docker 절차를 따른다.

## full 검증

dev와 full 데이터/모델 경로는 분리된다. 기본 dev와 동시에 실행하려면 README의
별도 Compose 프로젝트와 포트를 사용한다. 동일 포트에서 두 프로젝트를 띄우지 않는다.

```bash
SCALE=full docker compose up --build -d
SCALE=full docker compose exec api-server python scripts/smoke_test.py --benchmark
SCALE=full docker compose exec api-server python -m docker.quality --split valid
SCALE=full docker compose exec api-server python -m docker.quality --split test
SCALE=full docker compose exec api-server python -m docker.quality --split test --verify-existing
```

valid에서 데이터·모델·평가 설정/소스를 동결한 뒤 독립 test를 평가한다.
품질 수치만 재검사하려고 test를 반복 튜닝하지 않는다. smoke 실패는 nonzero다.
이 명령만으로 A/B·CT·제출 항목까지 최종 PASS가 되지는 않는다.
INTEGRATE에서 실제 full 운영 연결과 여섯 필수 검사를 추가로 확인해야 한다.

## 로컬 제출 검사

개발 환경이 없다면 `bash setup_env.sh . --role=A`로 준비한다.
호스트 실행에는 Docker 서비스 이름 대신 localhost 환경을 사용한다.

```bash
source scripts/local_env.sh
PYTHONHASHSEED=42 .venv/bin/python scripts/check_submission.py
.venv/bin/python scripts/check_submission.py --verify-existing
.venv/bin/python scripts/check_submission.py --verify-existing --require-ready
```

기본 명령은 파일/모듈·ignore·seed/타입 AST 감사·mypy·pip·실제 Redis 포함 pytest와
라이브 API 스키마를 검사하고 `docs/results/final_submission/`에 로그를 저장한다.
API가 없으면 BLOCKED로 기록한다. `--api-url`로 실제 서비스 주소를 지정할 수 있다.
`--verify-existing`은 원본 측정·소스·실행 로그·집계 JSON 해시를 재검사하며 새 pytest/모델 평가가 아니다.
기본 종료 0은 **B11 산출물 검증**의 통과다. 최종 준비가 미완료이면
`--require-ready`는 **종료 2**이며, 검사 오류/실패는 **종료 1**이다.
저장된 저장소 접근 확인은 확인 시각의 snapshot이며 제출 직전에 다시 확인한다.

## 산출물 보존

Git에는 코드·비밀값 없는 `.env`·설정·검사 결과만 포함한다.
`data/`, 이미지·임베딩·`models/`·HF 캐시·`.venv/`는 동일 config/seed로 재생성한다.
`.env.local`의 비밀값은 커밋하거나 출력하지 않는다. 설정 변경은 config YAML/환경변수로 한다.
호환되지 않거나 불완전한 기존 산출물은 오류로 보존하며 새 버전 경로를 사용한다.
`docker compose down`은 컨테이너를 정지/제거하지만 볼륨은 유지한다.
볼륨 제거·데이터 초기화는 이 절차에 포함하지 않는다.

## 확인한 범위

B10은 Linux ARM64 CPU에서 네 서비스·full 품질·원시 HTTP/Redis/후보 지연을 측정했다.
full 최초 추천 학습 준비 2,698.698초에는 기존 데이터·검색·HF 캐시 재사용이 포함된다.
full 재사용 준비는 77.544초였다. 새 클론에서 전체 데이터/모델을 처음부터 생성하는
시간과 Docker 재현은 미측정이다. 별도 clean clone의 코드/기본 설정 검사는
[clone 증거](../results/final_submission/clone.json)로 구분한다.
다른 CPU 아키텍처·GPU·다중 동시 부하의 지연은 보장하지 않는다.
