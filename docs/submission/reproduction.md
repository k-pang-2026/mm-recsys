# 실행과 재현

현재 기본 생성기는 v4.4이며 `data/full-v44`, `models/full-v44`를 사용한다.
v4.3 이전 산출물은 덮어쓰지 않는다. 검증 근거는
`docs/results/experiments/A/final_validation_20261112/`에 저장한다.
2026-10-20 v4.2의 [과거 실행 기록](../results/integration/20261020_full/report.md)은 별도로 보존한다.

## 시작

Docker Desktop/Engine을 실행한 상태에서 저장소 루트에서 입력한다.

```bash
docker info
docker compose version
docker compose up --build
```

기본은 상품 50,000개·사용자 10,000명·이벤트 1,000,000건이다.
API 단일 writer가 데이터 → EDA → CLIP 임베딩 → FAISS → Two Tower·DeepFM·GRU → Redis를 준비한다.
첫 실행은 학습 때문에 시간이 걸린다. 기존 호환 산출물은 검사 후 재사용한다.
다운로드한 CLIP 캐시와 Docker 의존성 레이어는 재사용할 수 있다.
API 8000, 대시보드 8501, Redis 6379를 사용한다.

다른 터미널에서 준비 상태를 확인한다.

```bash
curl --fail http://localhost:8000/ready
```

준비 전 `/health`는 200, `/ready`와 모델 API는 503이다.
준비 후 API 문서는 http://localhost:8000/docs, 대시보드는 http://localhost:8501 이다.

## PDF 결과 예시

새 Linux/WSL/macOS 클론은 `python3 scripts/demo_host.py --install`로 호스트 명령을 한 번 등록한다.
Windows는 `python scripts/demo_host.py <명령>`을 사용한다. 이후 실행 중인 배포를 자동으로 선택한다.

```bash
demo search --query-text "검정 오버핏 후드티"
demo recommend --user-id U000001
demo examples
```

마지막 명령은 실제 검색 → 실제 클릭 두 건 → 추천 → 5,000명/군·30일 합성 A/B → 별도 CT 통제 시연 순서다.
빠른 시연은 `--users-per-group 100 --days 7`을 추가한다. 출력 폴더는 매번 새 경로를 사용한다.
상품·점수·시간·통계는 실행값이며 예시 숫자를 고정하지 않는다.
CT 통제 시연은 약한 초기 모델에서 실제 세 모델 학습·승격·HTTP 교체·롤백을 확인하며 운영 개선 측정과 구분한다.

## 품질·지연 검증

학습 워커와 다른 배포를 중지하고 한 배포에서 측정한다. full A/B와 CT 학습도 순서대로 실행한다.

```bash
docker compose stop simulator
docker compose exec api-server python scripts/smoke_test.py --benchmark --output docs/results/docker/runtime-v44/full/quality/smoke_full.json
demo evaluate --split valid
demo evaluate --split test
```

valid 통과 후 config·소스·데이터·모델을 동결해야 test가 실행된다.
전체 catalog Recall@300·전체 사용자 cohort·원래 품질/지연 기준을 그대로 적용한다.
CPU 허용 오차로 기준을 완화하거나 test 정답을 튜닝하지 않는다.

## 실제 CT 수집과 실행

기본 시뮬레이터는 Markov 피처 갱신, 실제 API 추천에 귀속된 합성 비클릭·클릭·구매 수집,
CT 자동 감시·재학습을 함께 수행한다. CT는 API와 같은 루프백 네트워크로만 모델 교체를 요청한다.
모든 전송 기록에 `synthetic: true`를 남긴다. 일반 Markov 로그 자체를 노출 정답으로 바꾸지 않는다.

```bash
docker compose start simulator
# 기본 CT 감시·자동 트리거 기록
docker compose logs -f simulator
# 지연 측정 전에는 수집과 CT를 함께 중지한다.
docker compose stop simulator
```

`demo ab`·`demo ct --drill`은 자동 CT와 같은 잠금으로 순차 실행한다.
수집만 필요하면 `CT_AUTO_TRAIN=0 docker compose up -d simulator`로 다시 생성한다.
10,000건은 학습 트리거이며 성공 보장이 아니다. train/valid에 성숙한 양성·음성 라벨이 부족하면
`WAITING_FOR_LABELS`로 대기한다. 원래 8/1/1 시간순 분할과 귀속 기간을 유지하며,
valid 개선 기준을 통과한 후보만 승격한다. 미달이면 기존 모델과 이유를 표시한다.
데이터 수집이 중단된 상태에서 시계만 기다려도 분할 종료 시점이 바뀌지는 않는다.

Python 로컬 검사는 `.venv/bin/python`을 사용한다. 전체 회귀 검사는 실제 Redis와 프로젝트 테스트 플러그인을 연결한다.

```bash
PYTHONHASHSEED=42 RUN_REDIS_TESTS=1 REDIS_HOST=127.0.0.1 REDIS_PORT=6379 .venv/bin/python -m pytest -q -p src.serving.pytest_support tests
.venv/bin/python -m mypy --explicit-package-bases src scripts dashboard docker
```

H&M·Retailrocket·DeepFashion의 추가 검증 범위는 [사용자 전달 강사 결정](dataset_scope.json)을 따른다.
원격 푸시·PR과 외부 과제 제출은 로컬 구현·검증과 별도다.
