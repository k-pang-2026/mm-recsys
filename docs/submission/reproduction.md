# 실행과 재현

저장소: https://github.com/k-pang-2026/mm-recsys

## 현재 full 4.2 통합 결과 재검증

2026-10-20 실행은 [현재 보고서](../results/integration/20261020_full/report.md)를 따른다.
사용자의 full 평가 원본을 보존·재사용하며 새 A/B·CT·Compose·HTTP·제출 검사는
`docs/results/integration/20261020_full/`에 분리한다. 현재 기본 API/대시보드 포트는
8000/8501이다. 아래 명령은 필수 검사를 모두 완료한 뒤 저장된 결과를 검증·연결한다.

```bash
source scripts/local_env.sh
SCALE=full PYTHONHASHSEED=42 .venv/bin/python scripts/check_submission.py \
  --verify-existing --require-ready \
  --output-dir docs/results/integration/20261020_full/submission
SCALE=full PYTHONHASHSEED=42 .venv/bin/python scripts/publish_integration_dashboard.py \
  --submission docs/results/integration/20261020_full/submission/checks.json \
  --output docs/results/docker/runtime/full/evaluation_full_test.json
```

전체 full A/B와 CT 학습·비교는 순차 실행한다. 이번 7.5GiB Docker 환경에서
두 API와 A/B·CT를 병렬 실행한 실패를 [별도 기록](../results/integration/20261020_full/parallel_load_failure.json)에
보존했다. 지연 측정은 검증용 중복 배포와 학습 워커를 종료한 뒤 단일 기본 배포에서 수행한다.
대시보드는 **결과 새로고침** 후 test 결과의 최종 판정·A/B·CT 근거를 표시한다.
품질 평가나 시뮬레이터 재생만으로 필수 통합 검사를 대체하지 않는다.

## 이전 full 4.1 통합 실행 환경과 버전 이관

현재 통합 실행과 최초 실패·재검사 기록은 [INTEGRATE 보고서](../results/integration/report.md)를 따른다.
generator 4.1.0은 생성에 영향을 주는 YAML mapping 순서를 fingerprint에 포함한다.
준비 설정도 키 순서를 보존한다. 이전 4.0.0 데이터/모델은 자동 덮어쓰기하지 않으며,
기존 경로에서 fingerprint가 다르면 중단한다. 새 클론의 빈 data/models 또는 새 버전 경로를 사용한다.

이번 full 검증은 원격 main b40712a clone에 현재 통합 변경을 적용한 독립 경로에서 수행한다.
포트는 API 19000·Streamlit 19501·Redis 17379이며 기존 개발 경로를 보존한다.
CLIP 사전 학습 다운로드 캐시와 Docker 의존성 레이어만 재사용하고,
데이터·임베딩·FAISS·추천 모델은 새로 생성한다. 전체 완료 전에는 기동을 재현 PASS로 집계하지 않는다.

`integration_config.yaml`은 이 머신의 검증용 artifact 별칭을 가리키는 full 설정 snapshot이다.
새 클론의 기본 기동은 아래 `config.yaml` 경로를 사용하며 이 별칭이나 `/tmp` 경로에 의존하지 않는다.
현재 머신에서 최종 제출 검사를 재검증할 때는 다음 환경과 별도 결과 경로를 사용한다.

```bash
SCALE=full CONFIG_PATH=docs/submission/integration_config.yaml PYTHONHASHSEED=42 \
  .venv/bin/python scripts/check_submission.py --verify-existing --require-ready \
  --output-dir docs/results/integration/submission
```

이 명령은 최종 checker 결과가 실제 생성된 뒤 사용할 수 있다. 실행 중 상태는 progress.json에 공개한다.
사용자가 전달한 강사 결정에 따라 H&M·Retailrocket·DeepFashion은 개발 후 추가 검증용이다.
필수 acceptance는 합성 full 데이터로 확인하며 [결정 원본](dataset_scope.json)을 보존한다.

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
기본 준비 제한은 21,600초다. INTEGRATE full의 빈 데이터·모델 경로 준비는
2,725.892초였으며 HF 다운로드 캐시와 의존성 레이어는 재사용했다.
최초 다운로드와 이미지 빌드 시간까지 포함한 수치는 아니다.

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
full 재사용 준비는 77.544초였다. 이 값들은 과거 B10 측정이다.
INTEGRATE의 별도 원격 clone+통합 patch에서는 빈 data/models에서 전체 생성·학습을
2,725.892초에 완료했다. [실제 준비](../results/integration/preparation_first_full.json)와
[실행 소스·재현 근거](../results/integration/fresh_checkout.json)를 확인한다.
별도 B11 clean clone의 코드/기본 설정 검사는
[과거 clone 증거](../results/final_submission/clone.json)로 구분한다.
다른 CPU 아키텍처·GPU·다중 동시 부하의 지연은 보장하지 않는다.
