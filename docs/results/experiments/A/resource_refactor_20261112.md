# 기능 보존 및 리소스 리팩터링 검증

검토한 10개 개선안을 구현했다. 기존 데이터·모델과 시간순 평가 계약을 유지하며,
원본 모델이나 테스트 정답을 변경하지 않았다. 이 문서는 이번 변경의 실행 근거이며,
기존 `final_acceptance.json`을 새로운 소스의 최종 제출 판정으로 재사용하지 않는다.

## 구현 범위

| 항목 | 구현 |
|---|---|
| 성능 저하 CT | 활성 모델의 충분히 성숙한 CTR/HitRate 관측이 기준 이하이면 로그 임계치 미만에서도 재학습 |
| CT 재시도 | 입력·모델·설정이 같으면 재시도 생략, 라벨 대기·성능 저하 재시도는 기본 300초 간격, 작업자 재시작 후에도 상태 유지 |
| CT 조회 | 최근 요청 및 귀속 이벤트 시간 인덱스와 범위 조회 |
| CT 로그 표시 | 로그 전체 크기와 관계없이 끝에서 제한된 바이트만 읽어 최근 기록 표시, 손상 레코드 집계 유지 |
| 학습 설정 | 세 모델의 `max_grad_norm`을 설정으로 분리, 기본값 10.0에 한정한 과거 번들·Docker 준비 호환 처리 |
| 타입 | ASGI 요청 처리기와 추천 생성자 타입, 기존 저장소들이 공유하는 조회 인터페이스 |
| A/B 초기화 | 검증된 데이터와 번들 메타데이터를 재사용하고 그룹별 상태·잠금·설정 분리 유지 |
| 평가 라벨 | 필요한 분할만 생성, CT valid 평가도 같은 함수 사용 |
| 랭킹 특성 | 실시간 DataFrame 생성과 정규화 왕복 제거, 학습·서빙의 항목 특성 및 정규화 공유 |
| 후보 검색 | 제외 목록이 비었을 때 5만 개 상품 집합 복사 생략 |

## 검증 결과

- 전체 회귀 검사: **485 passed**, 외부 라이브러리 deprecation warning 2건.
- 기본 mypy: **123개 파일 통과**. 검색 처리기·추천기의 추가 엄격 검사: **2개 파일 통과**.
- 실제 full 데이터·모델의 추천 111건: 상품·순서·사유·탐색 표시·세션 결과 동일.
  정규화 왕복 제거로 발생한 점수의 최대 부동소수점 차이는 `2.384185791015625e-7`.
- 같은 모델로 그룹당 20명·2일 A/B를 실행한 결과와 번들 메타데이터가 전후 동일.
  이는 full 규모의 5,000명/그룹·30일 A/B 재측정은 아니다.
- 실제 Docker API의 JSON·multipart·잘못된 입력·세션 추천 및 대시보드 HTTP 검사 통과.
- 소규모 CT에서 실제 세 모델 학습, paired valid 승격/유지, 동시 HTTP 요청, 재로딩,
  롤백, 손상 번들 거부 및 이벤트 중복 소비 방지 통과.
- 별도의 소규모 CT 상태에서 미처리 신규 이벤트 **0건**으로 성능 저하 트리거가 실행됨.
  실제 재학습의 CTR AUC가 **0.5 → 0.908127**로 개선돼 승격됐고 이후 원래 버전으로 롤백함.
  이 수치는 의도적으로 약한 초기 모델을 사용하는 통제된 검증이며 운영 full 모델 개선을 뜻하지 않는다.
- full valid/test 품질·지연 기준은 **각각 11개 모두 통과**했다. 상품 50,000개·사용자
  10,000명·이벤트 1,000,000건을 유지했고, valid 이후 소스·설정·모델을 동결해 test를 실행했다.
  현재 작업 폴더와 평가 근거의 소스·모델 등 88개 파일 해시도 일치한다.
- 같은 데이터의 이전 full test 결과와 비교한 품질 지표 7개는 모두 정확히 같다.
  테스트 정답·대상 사용자·후보 수·기준값을 바꾸지 않았다.

| full test 품질 | 실측 | 기준 |
|---|---:|---:|
| MRR | 0.925000 | ≥0.55 |
| NDCG@10 | 0.925000 | ≥0.50 |
| Recall@300 | 0.745793 | ≥0.30 |
| CTR AUC | 0.965785 | ≥0.70 |
| HitRate@50 | 0.665145 | ≥0.20 |
| NDCG@50 | 0.329914 | ≥0.08 |
| Coverage | 0.374480 | ≥0.20 |

이번 리팩터링의 구현·회귀·품질 검증은 완료했다. 전체 규모 30일 A/B 재측정, 운영 데이터의
CT 개선·승격 확인, 최신 소스 기준 B11 최종 제출 집계는 별도 미수행 범위다.
따라서 이번 품질 보고서의 `quality_status=PASS`와 최종 제출 `acceptance=UNMEASURED`를 구분한다.

## 자원 및 지연 측정

동일한 full 카탈로그·기존 모델, CPU Torch 4스레드, 10회 예열 후 101회 순차 내부 호출이다.
전체 회귀 검사와 일부 시간이 겹친 단일 전후 실행으로, 수치는 이 실행의 관측값이다.

| 측정 | 변경 전 | 변경 후 |
|---|---:|---:|
| 추천 중앙값 | 19.48ms | 11.67ms |
| 추천 p95 | 21.40ms | 13.41ms |
| 랭킹 특성 생성 중앙값 | 10.92ms | 1.69ms |
| 프로세스 최고 RSS | 1,712.38MiB | 1,486.63MiB |
| A/B 초기화 | 27.04초 | 26.02초 |
| 주요 Parquet 파일별 읽기 | 2회 | 1회 |
| 모델 체크포인트별 로딩 | 2회 | 1회 |

이와 별도로 회귀 검사·CT 학습 종료 후 단일 API 스택에서 HTTP를 측정했다.
각 모드 10회 예열·100회 순차 요청이며 API의 Torch/OpenMP 예산은 2스레드다.

| HTTP p95 | 실측 | 기준 |
|---|---:|---:|
| 텍스트 검색 | 19.51ms | ≤200ms |
| 이미지 검색 | 72.05ms | ≤200ms |
| 혼합 검색 | 82.19ms | ≤200ms |
| 추천 | 19.76ms | ≤200ms |

## 근거와 재현

- [최종 검증 집계·근거 해시](resource_refactor_20261112/verification.json),
  [품질 평가 진행 로그](resource_refactor_20261112/docker-quality.txt),
  [동결 근거 무결성 검사](resource_refactor_20261112/quality-verify.txt).
- [전후 비교 집계](resource_refactor_20261112/comparison.json),
  [변경 전 소스·모델 식별자](resource_refactor_20261112/before.json),
  [변경 후 소스·모델 식별자](resource_refactor_20261112/after.json).
- [전체 테스트](resource_refactor_20261112/full-tests-final.txt),
  [기본 타입 검사](resource_refactor_20261112/mypy-final.txt),
  [엄격 타입 검사](resource_refactor_20261112/strict-final.txt).
- 초기 전체 검사에서 기존 mock 함수가 새 키워드 인자를 받지 못한 2건은
  [원래 로그](resource_refactor_20261112/full-tests-before-fixture-fixes.txt)와
  [수정 후 재검증](resource_refactor_20261112/recheck-failures.txt)을 보존했다.
- [Docker 준비·HTTP 근거](resource_refactor_20261112/docker/smoke_full.json).
- [full valid 품질](resource_refactor_20261112/docker/quality_full_valid.json),
  [동결된 full test 품질](resource_refactor_20261112/docker/quality_full_test.json).
- [CT 전체 수명주기](resource_refactor_20261112/ct_lifecycle.json),
  [성능 저하 재학습](resource_refactor_20261112/ct_degradation.json),
  [재현 스크립트](resource_refactor_20261112/verify_degradation.py).

```bash
REDIS_HOST=127.0.0.1 REDIS_PORT=6379 RUN_REDIS_TESTS=1 PYTHONHASHSEED=42 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  .venv/bin/python -m pytest -q -p src.serving.pytest_support tests
.venv/bin/python -m mypy --ignore-missing-imports src dashboard docker scripts/prepare_all.py
docker compose up --build -d
```

위 품질 근거의 소스·모델·설정과 valid 동결 상태는 다음 명령으로 확인한다.
이는 새 측정이 아니라 저장한 근거의 무결성 검사다.

```bash
docker compose run --rm --no-deps --pull never -T \
  -e QUALITY_RESULTS_DIR=docs/results/experiments/A/resource_refactor_20261112/docker \
  -e RUNTIME_RESULTS_DIR=docs/results/experiments/A/resource_refactor_20261112/runtime \
  api-server python -m docker.quality --split test --verify-existing
```

새 학습·데이터 디렉터리는 기존 경로를 덮어쓰지 않는다. CT 재현 스크립트의 작업 경로와
결과 경로도 재실행할 때 새 경로로 변경해야 한다. 커밋·원격 푸시는 수행하지 않았다.
검증용 API·대시보드 컨테이너는 종료했고 Redis만 실행하는 기존 상태로 복원했다.
모델·데이터·볼륨은 유지했다.
