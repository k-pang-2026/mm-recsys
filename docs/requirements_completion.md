# PDF·첨부 요구사항 통합 검증 (2026-11-07)

이 작업은 첨부 텍스트 1~10번을 통합 보완한다. 과거 PASS는 현재 실행 결과로 사용하지 않는다.
새 실행 근거는 `docs/results/integration/20261107_requirements/`에 모은다.
최종 요구사항별 판정은 해당 폴더의 `requirements.json`과 이 문서의 후속 측정 표를 따른다.

## 해석과 데이터 버전

- PDF p.3~6 필수 기능·평가 프로토콜, p.8~9 환경·측정 조건, p.12~14 동료 평가를 대상으로 한다.
- PDF p.6~7 Query Understanding, MMR, ONNX, Thompson Sampling은 선택 보너스다.
- PDF p.9~12 상품 ID·점수·전환율·p-value·학습 버전은 참고 예시이며 합격 목표나 출력 정답이 아니다.
- 외부 H&M·Retailrocket·DeepFashion은 사용자가 전달한 강사 결정
  [`dataset_scope.json`](submission/dataset_scope.json)에 따라 선택 검증이다. 이번에 다운로드하지 않았다.
- **2026-11-07 사용자 확인: Ranking AUC ≥ 0.70은 CTR에 적용하고 CVR AUC는 별도로 보고한다.**
  CVR이 낮거나 양성이 부족하면 그대로 보고하며 CTR 통과를 CVR 개선으로 해석하지 않는다.
- 생성기 v4.3은 브랜드충성형에만 `preferred_brand_probability: 0.98`을 명시한다.
  나머지 페르소나의 설정, 목표, 분할, seed, 학습 표본·정답은 수정하지 않았다.
  가성비는 품질·효용 데이터가 없는 저가격 선호 대리모형이다.
- 새 기본 경로: dev=`data/dev-v43`, `models/dev-v43`; full=`data/full-v43`, `models/full-v43`.
  과거 `data/full`, `models/full` 및 과거 결과는 보존한다. 설정 변경으로 호환성이 깨지면
  새로운 `data_dir`, `split_dir`, `model_dir`로 분리한다. 준비 스크립트는 기존 파일을 덮어쓰지 않는다.
- 실시간 Redis namespace도 데이터 경로별로 분리한다. 대시보드 EDA는 해당 배포의 고정 생성 데이터이며,
  이후 live stream·CT snapshot은 별도의 관측/학습 기록이다.

## 새 환경 실행 (Bash·PowerShell 공통)

호스트에 Docker Desktop/Engine 및 Compose만 설치한다. Python·Torch·FAISS는 이미지에 포함된다.
Docker에 RAM 8GB 이상, CPU 4개 이상을 할당하고 호스트 RAM 16GB·디스크 50GB 이상을 권장한다.
이번 WSL 환경의 실제 자원·버전은 `environment.json`에 기록한다.

이번 머신에서 새 v4.3 데이터·인덱스·추천 모델이 없는 상태의 준비는 **1,885.96초**였고,
호환 산출물이 모두 있는 재시작 준비는 **91.07초**였다. CLIP 다운로드 캐시는
이미 준비된 환경이므로 신규 머신의 다운로드 시간까지 포함한 보장은 아니다.
실제 처음 상태와 6개 단계 종료 코드는 `preparation_initial.json`, `preparation_reuse.json`을 따른다.

```text
docker compose up --build
```

최초 준비는 데이터 → EDA → CLIP 다운로드 캐시/로컬 임베딩 → FAISS → Two-Tower·DeepFM·GRU → Redis 순서다.
`/health`는 준비 중에도 살아 있고 `/ready`는 모두 준비될 때까지 503이다.
대시보드와 시뮬레이터는 준비를 기다린다. 재시작은 같은 fingerprint의 산출물을 재사용한다.
컨테이너를 지워도 bind mount의 데이터·모델과 다운로드 볼륨은 남는다.
전역 별칭 없이 설치된 `docker-compose`도 같은 Compose 파일로 검증한다.
CLIP 최초 다운로드는 Hugging Face를 사용하며 이후 검색/추천 추론은 로컬 CPU로만 실행된다.

별도 터미널에서 준비와 서비스를 확인한다.

```text
docker compose logs -f api-server
docker compose ps
docker compose exec api-server python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/ready').read().decode())"
```

## CLI 시연

Windows PowerShell에서는 먼저 다음을 실행한다.

```powershell
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
```

아래 명령은 Bash·PowerShell에서 동일하다. stdout은 JSON, stderr는 한국어 진행 로그다.
`--output` 파일은 컨테이너에서 UTF-8로 저장한다. 큰 JSON을 터미널에 표시하지 않으려면
Bash는 `> result.json 2> run.log`; Windows PowerShell 5는
`cmd /c "docker compose exec -T ... > result.json 2> run.log"`로 원본 UTF-8 바이트를 보존한다.
PowerShell의 직접 `>`는 버전에 따라 UTF-16이므로 사용하지 않는다.

```text
docker compose exec -T api-server python scripts/demo.py search --query-text "검정 오버핏 후드티" --output docs/results/docker/runtime-v43/full/demo_text.json
docker compose exec -T api-server python scripts/demo.py search --query-image data/full-v43/images/P000001.jpg --output docs/results/docker/runtime-v43/full/demo_image.json
docker compose exec -T api-server python scripts/demo.py search --query-text "가방" --query-image data/full-v43/images/P000001.jpg --output docs/results/docker/runtime-v43/full/demo_hybrid.json
docker compose exec -T api-server python scripts/demo.py recommend --user-id U000001 --output docs/results/docker/runtime-v43/full/demo_recommend.json
docker compose exec -T api-server python scripts/demo.py session --user-id cli-session-v43 --product-id P000001 --category "tote bag" --event-id cli-session-v43-click-1 --output docs/results/docker/runtime-v43/full/demo_session.json
docker compose exec -T api-server python scripts/demo.py ct --output docs/results/docker/runtime-v43/full/ct_monitor.json
docker compose exec -T api-server python scripts/demo.py verify-peer-review --output docs/results/docker/runtime-v43/full/peer_review.json
```

이미지는 실제 파일을 읽는다. 저장소 `data/`는 컨테이너 `/app/data`로 마운트되어 있으므로
사용자 이미지도 `data/query.jpg`로 두고 `--query-image data/query.jpg`로 호출할 수 있다.
세션 재시도에는 같은 event_id를 사용한다. 새 클릭에는 새 ID를 사용한다.
상품 카테고리는 대시보드 원천 데이터에서 확인하며 임의 문자열을 넣지 않는다.

## 무거운 작업과 평가 순서

실시간 생성기를 잠시 멈추고 준비·평가·A/B·CT를 **순차** 실행한다.
모델 학습과 지연 측정을 동시에 실행하지 않는다. 별도 작업 컨테이너를 사용하여
API 컨테이너의 4GB 제한 안에 학습 프로세스까지 중복 적재하지 않는다.

```text
docker compose stop simulator
docker compose exec -T api-server python scripts/smoke_test.py --benchmark --output docs/results/integration/20261107_requirements/smoke_full.json
docker compose run --rm --no-deps --pull never -e QUALITY_RESULTS_DIR=docs/results/integration/20261107_requirements --entrypoint python api-server scripts/demo.py evaluate --split valid
docker compose run --rm --no-deps --pull never -e QUALITY_RESULTS_DIR=docs/results/integration/20261107_requirements --entrypoint python api-server scripts/demo.py evaluate --split test
docker compose run --rm --no-deps --pull never --entrypoint python api-server scripts/demo.py ab --users-per-group 100 --days 7 --output docs/results/integration/20261107_requirements/ab_demo.json
docker compose run --rm --no-deps --pull never --entrypoint python api-server scripts/demo.py ct --drill --output docs/results/integration/20261107_requirements/ct_drill.json
```

valid가 기준을 충족한 동일 데이터·모델·설정·소스만 test를 열 수 있다. 평가에는 전체 카탈로그,
미래 cart/purchase 고유 정답, 전체 사용자 cohort, BM25·Two-Tower·인기도 기준선을 사용한다.
A/B의 100명/군·7일은 빠른 실험 조건이며 PDF의 5,000명/군·30일 참고 결과로 표시하지 않는다.
옵션을 생략하면 config의 5,000명/군·30일을 실행한다. 음수·비유의 lift도 그대로 출력한다.

CT `--drill`은 별도 소규모 데이터·모델·registry와 실제 학습·HTTP 서버를 사용하는 제어 실험이다.
운영 품질 개선의 증거로 쓰지 않는다. 정상 경로의 명시적 재학습은 다음과 같다.

```text
docker compose run --rm --no-deps --pull never --entrypoint python api-server scripts/demo.py ct --train --output docs/results/docker/runtime-v43/full/ct_training.json
```

신규 로그 임계치를 충족할 때 기존 trainer·paired valid 평가·registry를 실행한다.
승격 후 API까지 교체하려면 API의 루프백 네트워크를 공유하는 별도 작업 컨테이너를 사용한다.
다음 명령은 실제 full CT 검증에 사용한다. Docker 메모리 전체 8GB 이상을 확보하고
시뮬레이터·A/B·품질 평가와 동시에 실행하지 않는다.

```text
docker run --rm --memory 4g --cpus 4 --network container:mm-recsys-api-server-1 --volumes-from mm-recsys-api-server-1 -e CONFIG_PATH=models/full-v43/.docker/config.yaml -e SCALE=full -e PYTHONHASHSEED=42 -e DOCKER_RUNTIME=1 -e OMP_NUM_THREADS=1 -e MKL_NUM_THREADS=1 -e OPENBLAS_NUM_THREADS=1 -e TOKENIZERS_PARALLELISM=false -e HF_HOME=/app/.cache/huggingface --entrypoint python mm-recsys-api-server scripts/demo.py ct --train --reload-url http://127.0.0.1:8000 --output docs/results/docker/runtime-v43/full/ct_training.json
```

기본 Compose 프로젝트 이름 기준이다. 이름을 바꿨다면 `docker compose ps`의 API 컨테이너 이름을 사용한다.
승격하지 않으면 기존 모델을 유지한다. 모니터링 기본 주기는 60초, 재학습 임계치는 신규 이벤트 10,000건이다.
운영 롤백은 `ct --rollback VERSION --reason "사유" --reload-url http://127.0.0.1:8000`이다.

## Streamlit 시연

`http://localhost:8501`에 접속한다. 검색 → 추천 → A/B 실험 → 시스템의 기존 화면을 유지한다.
EDA·구매 이력에서 데이터 fingerprint, 분모·제외 수, 페르소나 분포와 사용자 구매 원장을 확인한다.
상품·CLIP에서 `P000001`의 실제 이미지·속성·설명문·CLIP 입력과 item_ids 인덱스,
벡터 차원·norm·일부 값·고정 revision을 확인한다.
추천 실행 후 상품의 “이 상품 클릭 후 추천 비교”를 누르면 실제 `/api/event`가 호출되고
추천 전후 응답과 session_context가 표시된다. 재실행할 때 저장된 응답과 실시간 응답을 혼동하지 않는다.
브라우저 캡처·실행 기록과 AppTest 결과는 따로 저장한다.

실시간 생성 배치는 Redis 갱신과 함께 CT journal에 event_id 단위로 저장한다.
`generated_at`을 실제 관측 시각으로 사용하며, 원래 합성 타임라인은 원본 배치 파일에 보존한다.
추천 request에 연결되지 않은 합성 배치를 CTR/HitRate의 성공 노출로 계산하지 않는다.
따라서 신규 로그가 많아도 성숙한 attribution 표본이 없으면 모니터 지표는 null/UNMEASURED다.

설정 전환 검사는 `recommend.scoring.strategy`의 유사도순/최신순,
`simulator.personas.*.ratio`, `simulator.taxonomy` 변경을 실제 생성·추천 테스트로 확인한다.
행동 전환은 `simulator.transitions`의 search/view/purchase와 페르소나별 `cvr`로 조정한다.
cart에서 구매로 갈 확률은 페르소나 cvr에서 파생하는 규칙이 우선한다.

## 데이터 수정의 실제 근거

동일 seed 42의 full 생성 데이터를 분석했다. 아래 집중도는 구매자별 최다 구매 브랜드 비중의
단순 평균이며, 구매 이벤트 전체를 합친 브랜드 점유율과 구분한다.

| 페르소나 | v4.2 브랜드 집중도 | v4.3 브랜드 집중도 | v4.3 구매 가격 백분위 | v4.3 구매/view |
|---|---:|---:|---:|---:|
| 가성비 | 0.8723 | 0.8767 | 0.2951 | 0.0521 |
| 브랜드 충성 | 0.8560 | 0.9392 | 0.4496 | 0.1044 |
| 신중형 | 0.8982 | 0.9026 | 0.3410 | 0.0344 |
| 충동형 | 0.8534 | 0.8601 | 0.3757 | 0.1435 |
| 실용형 | 0.8632 | 0.8631 | 0.3537 | 0.0712 |
| 트렌드형 | 0.8612 | 0.8618 | 0.4098 | 0.0892 |

수정 전에는 브랜드 충성형의 집중도가 신중형보다 낮아 해당 검사가 FAIL이었다.
수정 후에는 여섯 집단 중 가장 높다. 가격 백분위는 소분류 내 전체 상품 기준이고,
구매/view는 EDA 비율이며 A/B의 구매/노출 CVR과 다른 지표다.
원본은 `data_audit_before.json`, `data_audit.json`에 있으며 실패 결과를 덮어쓰지 않았다.

## 검증 근거를 읽는 방법

`requirements_v43.json`은 PDF 페이지·구현·명령·검사 방법을 연결한 목록이고,
`20261107_requirements/requirements.json`은 이번 실행 결과의 최종 집계다.
`scripts/verify_requirements.py`는 실제 평가를 다시 실행하지 않고 새 근거들의 fingerprint,
valid 동결, 현재 소스 해시, 개별 지표·기능 검사 결과를 확인한다.

```bash
.venv/bin/python scripts/verify_requirements.py --results docs/results/integration/20261107_requirements
RUN_REDIS_TESTS=1 REDIS_HOST=127.0.0.1 REDIS_PORT=6379 .venv/bin/python -m pytest -q -p src.serving.pytest_support tests
```

호스트 테스트에는 `REDIS_HOST=127.0.0.1`을 사용한다. 컨테이너 간 주소 `redis`를 그대로
호스트에서 사용해 실패한 최초 로그는 `pytest_container_hostname_failure.*`에 보존한다.
최종 전체 검사와 명시적으로 실행한 Redis 추가 검사는 동일 testcase ID로 합쳐 중복 집계하지 않는다.
`before_auxiliary_log_completion/`은 보조 CLI 한국어화 전 valid 결과다.
이후 test를 열기 전에 소스를 확정하고 valid를 다시 동결했으며, 모델·정책·목표는 조정하지 않았다.

## 이번 full test 측정

valid에서 선택·동결한 v1.0을 test에서 한 번 평가했다. 상품 50,000개·사용자 10,000명·
이벤트 1,000,000건, seed 42이며 원본은 `quality_full_test.json`이다.
지연은 별도로 학습·시뮬레이터를 멈추고 warmup 10회 후 단건 100회 측정한
`smoke_full.json`을 연결했다. 첫 요청·동시 부하 성능은 이 표의 범위가 아니다.

| 지표 | 실제 값 | 기준 | 판정 |
|---|---:|---:|---|
| mrr | 0.931667 | ≥ 0.55 | PASS |
| ndcg_at_10 | 0.931667 | ≥ 0.5 | PASS |
| recall_at_300 | 0.755056 | ≥ 0.3 | PASS |
| auc | 0.966322 | ≥ 0.7 | PASS |
| hit_rate_at_50 | 0.678373 | ≥ 0.2 | PASS |
| ndcg_at_50 | 0.332781 | ≥ 0.08 | PASS |
| coverage | 0.364100 | ≥ 0.2 | PASS |
| search_p95_ms | 88.290973 | ≤ 200 | PASS |
| recommend_p95_ms | 36.093945 | ≤ 200 | PASS |
| candidate_p95_ms | 4.503044 | ≤ 100 | PASS |
| feature_p95_ms | 0.322686 | ≤ 10 | PASS |

CTR 평가 노출 217,236건·클릭 양성 54,309건. CVR AUC는 **0.540255**, 클릭 노출 54,309건·구매 양성 3,514건이다.
CTR 기준을 충족했지만 CVR의 구분 성능이 높다는 의미는 아니다.

고정 cohort는 10,000명이며 미래 정답이 있는 사용자는 7,005명, 빈 정답은 2,995명이다.
콜드스타트 300명 중 정답 사용자는 9명이다. 빈 정답 사용자는 계약대로 Recall/HitRate
평균에서만 제외하며 Coverage는 전체 10,000명으로 계산했다. cutoff 당시 eligible
카탈로그는 48,872개이고 미래 등록으로 검색 불가능한 정답 상품 71개도 정답에서 지우지 않았다.

전체 파이프라인의 기준선 대비 상대 변화는 다음과 같다. 음수 값도 보존한다.

| 기준선 | HitRate@50 | NDCG@50 | Coverage |
|---|---:|---:|---:|
| train_popularity | +896.23% | +1943.24% | +36310.00% |
| two_tower | +25.75% | +98.71% | -33.76% |
| deepfm | -3.73% | -13.32% | -17.33% |

일반화·품질 향상은 이 합성 데이터와 평가 계약 범위에서 해석한다.
실제 사용자의 구매 전환 개선을 입증한 결과가 아니다.

측정 환경은 Windows 11 ARM의 WSL2/Docker Linux aarch64, CPU 전용이다.
API 컨테이너는 4 CPU·4GB 제한, Python 3.11.18·Torch 2.6.0+cpu·FAISS 1.9.0이다.
서빙 Torch/FAISS와 OMP/MKL/OpenBLAS는 각각 2 threads, 독립 후보 벤치는
4 threads로 기록됐다. 단일 배포, 상주 모델·인덱스, 응답 캐시 없음, HTTP 호출마다
새 연결을 사용했다. 이미지 추론은 동일 FP32 가중치의 TorchScript 최적화이며
벡터 최대 오차 3.13e-7을 확인했다. 세부 조건과 원시 100개 표본은 `smoke_full.json`에 있다.

## 이번 A/B 실험

인기순(control)과 전체 추천 파이프라인(treatment)을 사용자 단위로 무작위 배정했다.
100명/군, 7일, seed 42, 7,000노출/군의 합성 실험이며 원본은 `ab_demo.json`이다.
CTR은 클릭/노출, CVR은 구매/노출이고 반복 노출은 사용자 cluster로 처리한다.

| 지표 | Control | Treatment | 상대 변화 | 차이 95% CI (%p) | p-value |
|---|---:|---:|---:|---:|---:|
| CTR | 24.4571% | 20.4857% | -16.24% | [-5.6469, -2.2959] | 3.38871e-06 |
| CVR | 1.2714% | 0.9714% | -23.60% | [-0.6599, +0.0599] | 0.102291 |

- control: 클릭 1,712건, 구매 89건, 구매자 56명.
- treatment: 클릭 1,434건, 구매 68건, 구매자 49명.

검사 PASS는 실험·통계 계산이 올바르게 수행됐다는 의미다. CVR 상대 변화는 음수이며
95% CI가 0을 포함하므로 개선이나 유의한 차이를 주장하지 않는다. CTR은 이 합성 실험에서
감소했다. 두 군의 모든 사용자가 한 번 이상 클릭하여 any_click 사용자 위험 차이의
경계 분산은 퇴화 상태다. 원본의 low_expected_counts·asymptotic_reliable 표시를 보존한다.

## 실패 보존과 회귀 검사

전체 검사 391개 통과와 명시적 Redis 추가 검사 5개 통과를 testcase ID로 합쳐
**396개 통과**로 집계한다. 초기 호스트 검사에서 컨테이너 DNS 이름 `redis`를 사용해
실패했던 로그는 `pytest_container_hostname_failure.*`에 남겼다.

full Compose에서 격리 CT 시연을 실행하자 실제 학습·승격·롤백 후 보고서 수집이
실패했다. 작은 fixture가 환경의 `SCALE=full`을 상속해 `*_full.json`을 썼는데
검사기는 `*_dev.json`을 찾았다. `src/ct/verify_ct.py`에서 fixture 규모를 dev로
명시한 뒤 기존 CT 테스트 18개를 재실행해 통과했다. 이 18개는 전체 396개와
중복이므로 별도로 더하지 않는다. 실패 원문은 `ct_drill_full_scale_failure/`에
보존하고 새 격리 실행의 결과를 사용한다. full 품질 평가 소스·모델은 변경하지 않았다.

60초 주기 확인에서 컨테이너 UTC 시각 차이는 약 58.5초로 관측됐다. VM 벽시계
보정의 영향을 받는 최초 검사 실패는 `ct_watch_wall_clock_probe.*`에 보존했다.
외부 호스트 monotonic clock으로 다시 측정한 실제 두 관측 간격은
**60.0187초**였다(`ct_watch.json`). 설정값·허용 기준은 변경하지 않았다.

대시보드 API 링크는 컨테이너 내부 주소 대신 사용자의 공개 주소 `/docs`로 연결한다.
기본은 `http://localhost:8000/docs`이며 `API_PORT` 또는 `PUBLIC_API_URL`을 따른다.
서버 간 HTTP 호출은 내부 주소를 계속 사용한다. 이 변경의 회귀 검사 12개 중 신규
주소 검사 3개를 포함하여 이 시점의 고유 테스트는 **399개 통과**였다.
아래 CT 라벨 동등성 검사를 포함한 최종 집계는 **400개 통과**다.

WSL의 캡처용 Chromium에는 처음 한글 글꼴이 없어 네모로 표시됐다. 설치된 Windows
맑은 고딕을 임시 fontconfig에 연결한 뒤 한글 화면을 다시 캡처했다. 글꼴 파일은
저장소에 포함하지 않는다. 원래 캡처는 `browser_without_korean_font/`에 보존했다.
Windows PowerShell의 stdout/stderr·UTF-8 저장 검사와는 별도 브라우저 환경 문제다.

대시보드 갱신 직후 첫 브라우저 접근은 준비 전 연결 초기화로 실패했고
`browser_dashboard_startup_failure/`에 원문을 보존했다. 준비 endpoint 200 확인 후
재실행한 `browser_public_link_ready`는 API 문서 링크 HTTP 200, 6개 탭,
상품 이미지와 실제 클릭 전후 비교를 모두 통과했다. 최종 캡처는 `browser_*.png`다.

화면 상단의 기존 `최종 종합 품질: UNMEASURED`는 저장된 평가 보고서의 기존
acceptance 상태다. 이 통합 보완의 판정은 `requirements.json`에서 별도로 집계하며,
과거 B11 게이트·원격 제출 승인 상태를 덮어쓰지 않는다.

JSON 원본을 파이프로 받는 작업은 최초 `docker compose up --build`로 준비한 뒤
`docker compose run --pull never`를 사용한다. 이 옵션이 없으면 저장소의
`pull_policy: build`에 의해 Docker 빌드 진행 출력이 stdout에 붙을 수 있다.
실제 CT 모니터 명령에서 단일 JSON stdout과 한국어 stderr를 검증했다
(`compose_json_mode.json`). 코드 변경 후에는 먼저 명시적으로 이미지를 다시 빌드한다.
Docker 빌드·시작 로그는 별도 진단 로그로 보존한다.

```bash
docker compose run --rm --no-deps --pull never --entrypoint python api-server scripts/demo.py ct --json > ct.json 2> ct.log
```

PowerShell 5에서 같은 원본 바이트를 저장할 때는 앞의 UTF-8 설정 후
`cmd /c "docker compose run --rm --no-deps --pull never --entrypoint python api-server scripts/demo.py ct --json > ct.json 2> ct.log"`를 사용한다.

## full CT의 메모리 실패와 검증 재개

첫 정상 CT는 실제 신규 로그 **202,941건**으로 세 모델 학습을 모두 완료했지만,
paired valid 비교 중 4GB cgroup 제한에서 OOM으로 종료됐다. 원본 종료 코드 247,
`oom_kill=1`과 로그는 `ct_natural_oom_failure/`에 보존했다. API는 계속 실행됐다.
`build_from_journal`이 snapshot을 기록한 뒤에도 events·impressions와 SQL 조회 결과를
계속 보유하고 있어, 학습·검증에서 다시 읽은 데이터와 메모리가 중복됐다.
이 참조를 학습 전에 해제하고, 학습과 기존 모델 비교가 끝난 뒤 GC를 수행하도록 수정했다.

`resume_integration_ct.py --observed-journal`은 당시 registry 상태·captured watermark,
데이터 파일 해시, 세 모델 학습 보고서·checkpoint reload, staging registry의 번들 해시를
검증한 뒤 중단된 비교만 재개한다. 다른 학습이 실행 중이거나 부모 모델이 바뀌면 중단한다.
새로 들어온 이벤트를 이전 watermark에 포함시키지 않는다.

신규 로그는 트리거와 새 시간순 snapshot에 반영한다. 학습은 그 snapshot의 train만
사용하므로 누적 신규 로그 전부가 이번 gradient update에 사용됐다는 뜻은 아니다.
원래 관측 데이터의 일부가 새 시간 기준에서 train으로 편입될 수 있으며, 원래 full test
보고서·동결 모델과 새 CT valid 판정을 섞지 않는다. 새 CT test 구간은 선택에 사용하지 않는다.

복구 결과는 다음과 같다. 이 표는 원래 full test와 다른 새 CT valid 구간이다.

| 지표 | 기존 v1.0 | 후보 v1.1 |
|---|---:|---:|
| CTR AUC | 0.966698 | 0.967987 |
| CTR logloss | 0.139683 | 0.148345 |
| HitRate@50 | 0.613908 | 0.613184 |

CTR AUC 개선 폭 0.001289가 기존 승격 기준 0.001을 넘어 승격했다.
logloss와 HitRate는 악화되어 모든 지표가 개선됐다고 해석하지 않는다.
API가 v1.1을 로드한 상태에서 실제 추천 HTTP 응답을 확인했고, 반복 트리거는 WAITING이었다.
복구 프로세스의 메모리 peak는 3,646,160,896 bytes, 제한은 4,294,967,296 bytes이며
OOM 횟수와 종료 시 swap은 0이다(`ct_first_recovered_run/ct_recovery_memory.json`). 최초 실행·복구 근거는
`ct_first_recovered_run/`에서 확인한다.

자식 프로세스가 SIGKILL로 끝나 traceback이 없을 때도 CLI가 종료 시그널, OOM 확인,
보존된 학습 산출물 복구 안내를 한국어 stderr에 덧붙인다. 독립적인 작은 Python 자식에
SIGKILL을 보내 종료 코드·빈 stdout·한국어 안내가 유지되는지 검사했다(`child_sigkill.json`).
이 검사는 실제 모델 OOM 재실행과 구분한다.

정상 시간 경과 후에는 실제 CLI/API 검증 요청 122개·노출 1,220개가 성숙해
CTR=0.0 알림도 발생했다(`ct_natural_postfix.log`). 구매·클릭이 없는 검증 트래픽의
결과이며 실제 운영 사용자의 성능 저하로 일반화하지 않는다. HitRate@50은 표본 부족으로
null인 상태를 유지했다. 제어 실험의 강제 성숙 시계와 구분한다.


## 추가 메모리 병목과 valid 라벨 동등성

첫 메모리 수정 후 신규 로그 11,218건의 정상 full CT는 세 학습기를 완료했지만,
paired valid 중 **WSL 전체 메모리 부족**으로 종료됐다. worker peak는 3,657,965,568 bytes로
4GiB보다 낮았고, cgroup `oom=0`, `oom_kill=1`이었다. 종료 직전 WSL 가용 메모리는
약 155MiB, 2GiB swap은 모두 사용 중이었다. 이는 최초 컨테이너 한도 OOM과 별개이며
`ct_postfix_host_oom_failure/`에 보존했다. API는 HTTP 200을 유지했다.

CT의 `validation()`은 학습용 `prepare()`를 재사용하며 쓰지 않는 train 라벨까지
생성하고 있었다. 기존 `read_data`, `read_impressions`, `build_labels`로 동일한 valid
라벨만 생성하고, 분류 지표 계산 뒤 임시 배열을 해제하도록 바꿨다. 실제 생성 데이터에서
기존 `prepare()`의 valid 라벨과 모든 행·열·값이 같음을 회귀 검사했다. 시간 경계,
attribution, 전체 카탈로그·사용자와 승격 기준은 변경하지 않았다.
CT 검사 19개가 통과했으며 신규 동등성 검사 1개를 포함한 고유 회귀 검사는 400개다.
API·대시보드를 재시작해 누적 메모리를 정리한 뒤 보존된 v1.2 학습 결과를 검증한다.

복구 도구의 첫 모델 가정도 수정했다. 두 번째 CT snapshot의 parent fingerprint는
초기 데이터가 아니라 registry에 기록된 실제 부모 v1.1 데이터와 대조한다.
부모 버전·last_success_seq·watermark·모델·파일 해시 검사는 유지한다.
수정 전의 명시적 거부는 `ct_recovery_parent_fingerprint_failure/`에 보존했다.


두 번째 복구는 신규 로그 11,218건의 동일 snapshot에서 완료됐다.
기존 v1.1 / 후보 v1.2의 CTR AUC는 **0.967081 / 0.967548**, CTR logloss는
**0.149086 / 0.140579**, HitRate@50은 **0.620781 / 0.616034**였다.
분모는 CTR 56,240건, 정답 사용자 1,896명이다. AUC 개선 폭 0.000467은 기준
0.001 미만이므로 기존 v1.1을 유지했다. 같은 로그의 반복 트리거는 신규 0건·WAITING,
실제 API 활성 버전과 추천 응답도 확인했다.
메모리 peak **2,952,347,648 bytes**, 4GiB 한도, OOM 0회, 종료 시 swap 5,652,480 bytes였다.
원본은 `ct_second_recovered_run/`에 보존한다. 이는 중단된 비교 복구이며,
수정 후 정상 경로 전체 재실행과 분리해서 보고한다.


## 수정 후 정상 full CT 전체 실행

2026-11-07 08:12:13~08:46:12 UTC에 실제 신규 로그 **10,360건**으로 후보 v1.3을
학습했다. snapshot 작성, Two-Tower·DeepFM·GRU 학습, checkpoint 재로딩,
paired valid 비교, registry 판정, 반복 트리거와 실제 API 추천 확인까지 **중단 없이 통과**했다.
이는 앞선 실패·복구와 별개의 정상 경로 실행이다(`ct_execution.json`).

| 지표 | 기존 v1.1 | 후보 v1.3 |
|---|---:|---:|
| CTR AUC | 0.966278 | 0.966536 |
| CTR logloss | 0.152410 | 0.142116 |
| HitRate@50 | 0.610329 | 0.610329 |

CTR 표본 37,772건·정답 사용자 1,065명, 동일 valid fingerprint를 사용했다.
CTR AUC 개선 폭 **0.000258 < 0.001**이므로 **RETAINED**, 활성 v1.1을 유지했다.
처리 watermark는 231,932이며 같은 로그의 반복 실행은 신규 0건·WAITING이었다.
활성 모델 v1.1의 실제 추천 HTTP 응답도 성공했다. 과거 v1.1 승격과 격리 시연의
롤백 근거를 이 유지 판정과 구분한다.

worker의 메모리 peak는 **3,178,864,640 bytes (약 2.96GiB)**, 제한은 4GiB,
`oom=0`, `oom_kill=0`이었다. 종료 시 swap은 19,673,088 bytes다.
CPU 4개 제한을 유지했고, API·대시보드·Redis는 켜 두되 데이터 생성기는 학습 전에
정지했다. 원본 학습·판정 로그는 `ct_natural_postfix2.log`, 메모리는
`ct_postfix_memory.json`, 세 모델의 결과는 `ct_*_training_full.json`을 따른다.
초기 두 메모리 실패의 원문과 조건을 삭제하거나 성공 실행으로 덮어쓰지 않았다.


## 최종 서비스와 근거 확인

정상 CT 검증 후 `v1.0`으로 실제 롤백·HTTP reload하고 최신 소스 이미지로 재시작했다.
`final_runtime.json`은 **PASS**이며 API·대시보드·Redis·시뮬레이터 네 서비스가 실행 중이다.
API `/ready`, Windows PowerShell 접속, 실제 검색·추천 HTTP 응답을 확인했다.
`quality_verify_final`은 기존 full test의 동결 데이터·모델·설정·소스 identity 검사이며
**새로운 test 품질 측정이 아니다**. 앞에서 기록한 실제 full test 결과를 재사용 가능한지 확인했다.

현재 고유 회귀 검사 400개, 정적 검사 130개 소스 파일이 통과했다.
요구사항 50개와 동료 평가 질문 13개는 다음 집계기로 원본 근거·SHA-256을 검사한다.

```text
.venv/bin/python scripts/verify_requirements.py
```

최종 판정과 항목별 구현·명령·근거는 `requirements.json`, 코드 fingerprint는
`source_identity.json`, 커밋 대상 파일의 해시는 `artifact_manifest.json`에 기록한다.
원격 push·PR은 수행하지 않았으며 기존 `.env` 변경과 `data/.gitkeep` 삭제는 별도로 보존한다.
