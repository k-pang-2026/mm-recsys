# 멀티모달 검색 및 Multi-Stage 추천 시스템

팀장이 공통 개발 기반을 구현·검증해 `chore/shared-foundation` → main PR로 먼저 병합한 뒤,
세 사람이 독립 클론에서
Codex에 단계 실행만 지시해 검색·추천·서빙을 병렬 개발한다.

| 역할 | 이름 | 담당 | Codex 입력 |
|---|---|---|---|
| A(팀장) | 이제원 | 공통 준비, 검색, Docker·컨테이너 성능 검증, 제출 문서, 최종 통합 | `A 다음 단계 실행` |
| B | 박정욱 | Two Tower, DeepFM, 재랭킹, MAB, 세션 | `B 다음 단계 실행` |
| C | 박채영 | Redis, 서빙, 평가·대시보드, A/B, CT | `C 다음 단계 실행` |

C는 B9까지 플랫폼 PR을 완료·병합한다. A는 검색 `feat/A/search` 이후
Docker B10을 `feat/A/docker`, 제출 문서 B11을 `feat/A/submission`,
최종 통합을 `feat/integration`에서 순서대로 수행한다.
순서는 **C B9 → A B10 → A B11 → A INTEGRATE**이며, 각 의존성은 PR 병합된 main에서 가져온다.

첫 입력은 `B 개발환경 준비하고 다음 단계 실행`처럼 역할을 지정한다.
Codex가 setup·브랜치 준비·구현·검증·수정·로컬 commit을 수행하고 내용을 설명한다.
사용자가 확인해 푸시·PR 생성을 허가하면 Codex가 기능 브랜치를 push하고 main 대상 PR을
생성/갱신한다. 기능 완료 PR은 충돌·검증·CI·품질·필수 리뷰 조건을 확인해 자동 병합한다.
푸시는 설명·허가가 필요하며, 안전한 병합은 별도 확인 없이 수행한다. main 직접 푸시는 하지 않는다.
[사람이 따라 할 시작 가이드](docs/codex_quickstart.md),
[단계별 상세 요구사항](ai_step_prompts_optimized.md),
[병렬 작업·Git 계약](docs/team_workflow.md), [브랜치·PR 절차](docs/pr_workflow.md)를 참고한다.

```mermaid
flowchart LR
  Simulator[공통 시뮬레이터] --> Dataset[Catalog / Users / Events / Splits]
  Dataset --> Search[A: CLIP / FAISS]
  Dataset --> Candidate[B: Two Tower / FAISS]
  Candidate --> Ranking[B: DeepFM]
  Ranking --> Rerank[B: Re-ranking / MAB / Session]
  Store[C: Redis Feature Store] --> Rerank
  Search --> API[C: FastAPI]
  Rerank --> API
  API --> Dashboard[C: Evaluation / A-B / Streamlit]
  Dataset --> CT[C: Continuous Training]
  API --> Docker[A B10: Docker / 컨테이너 성능 검증]
  Dashboard --> Docker
  CT --> Docker
  Docker --> Submission[A B11: 제출 문서 / 제출 검증]
  Submission --> Integration[A INTEGRATE: 최종 통합 / full 검증]
```

환경을 직접 실행할 경우 한 명령으로 준비한다.

```bash
bash setup_env.sh . --role=B
# 선택: VS Code 대화 대신 CLI에서 다음 단계 실행
bash scripts/codex_run.sh B
```

기본 setup은 직접 의존성 설치, pip check, unit/contract 테스트, 시드42의 dev 데이터·이미지 생성,
시간 분할, train/valid 진단, 고정 CLIP revision 추론, Docker 상태/Compose 설정 검사를 수행한다.
Docker Desktop/Engine 실행·GitHub 인증·Codex 로그인은 각 컴퓨터의 선행 조건이다.
생략 옵션을 쓴 항목은 미측정이다. 실제 결과는 `.team/environment.json`과 docs/results에 저장한다.
데이터/.venv/캐시/모델은 커밋하지 않고 clone 후 동일하게 재생성한다.

공통 코드에는 설정/데이터/metric/API/메모리 FeatureStore가 구현되어 있다.
검색/추천 모델은 담당 단계에서 추가하며 모델 미준비 API는 503을 반환한다.
최종 품질·latency·Docker 재현 통과는 full 데이터의 B10/B11/INTEGRATE로 판정한다.

```bash
source scripts/local_env.sh
./.venv/bin/python -m pytest -q tests
```

## Docker로 전체 서비스 실행

Docker Engine/Desktop와 Compose v2 이상을 실행한 뒤 저장소 루트에서 시작한다.
`docker-compose`는 별도 설치된 구형 CLI 이름이며 아래 절차는 `docker compose`를 사용한다.

```bash
docker compose up --build -d
docker compose logs -f api-server
```

API만 준비 작업을 소유한다. 데이터 생성·검증 → 고정 revision의 CLIP 다운로드와 임베딩 →
FAISS 인덱스 → Two Tower·DeepFM·세션 학습 → Redis 프로필 warmup 순서다.
기존 데이터는 전체 manifest·이미지 checksum을 검사하고, 검색 산출물은 fingerprint와 checksum,
추천 산출물은 실제 모델 로딩으로 호환성을 확인한다. 완전한 호환 산출물만 재사용한다.
불완전하거나 다른 설정의 데이터·모델을 발견하면 보존하고 오류로 중단한다.
해당 파일을 삭제해 재시도하지 말고 새 버전의 data/model 경로를 설정한다.

| 서비스 | 로컬 주소 | 준비 상태 |
|---|---|---|
| 검색·추천 API | http://localhost:8000/docs | `/health`는 준비 중에도 200, `/ready`는 모델 로딩 완료 후 200 |
| Streamlit | http://localhost:8501 | HTTP health와 검색·추천 데모 제공 |
| Redis | localhost:6379 | ping healthcheck, 1GB 제한·allkeys-lru |
| 시뮬레이터 | 공개 포트 없음 | `/ready` 이후 생성된 이벤트를 시간순으로 API에 재생 |

준비 중 모델 API와 `/ready`는 503이다. 준비 서버에서 실제 API로 전환하는 순간에는
연결이 잠시 끊길 수 있으므로 readiness 검사는 재시도한다. 준비 실패는 API 컨테이너 종료와
로그에 표시한다. 준비와 대기 기본 제한은 각각 21,600초이며
`PREPARE_TIMEOUT_SECONDS`, `READY_TIMEOUT_SECONDS`로 조절한다.
준비 완료 뒤 다음 smoke를 실행한다. 검색 JSON·multipart 3모드, 기존·신규 사용자 추천,
실제 이벤트에 따른 세션 응답, 대시보드 HTTP를 확인한다.

```bash
docker compose exec api-server python scripts/smoke_test.py --benchmark
```

지연 검사는 각 모드 10회 warmup·100회 순차 HTTP, 후보 검색, 실제 Redis 조회의
p50/p95/p99와 원시 샘플을 기록한다. 검색/추천 200ms, 후보 100ms·300개, Redis 10ms 기준을
그대로 사용하며 미달 시 명령이 실패한다. 결과는 `docs/results/docker/smoke_dev.json`,
`docs/results/latency.json`에 남는다. HTTP 확인은 실제 브라우저 화면 검증과 구별한다.
고정 벤치마크는 초기 v1.0과 CT 재학습이 동시에 실행되지 않는 조건을 대상으로 한다.
승격된 release나 측정 중 버전 변경은 거부하며 해당 release는 별도로 평가한다.

학습·CT 로그와 새 평가는 `docs/results/docker/runtime/<scale>/`에 분리한다.
Streamlit도 이 경로를 읽으며 새 통합 평가가 없으면 미측정으로 표시하고 데모는 제공한다.
저장소의 다른 머신 평가를 새 컨테이너의 측정으로 표시하지 않는다.
기존 C 평가 CLI로 dev/valid 결과를 생성할 때는 다음과 같이 실행한다.

```bash
docker compose exec -e CONFIG_PATH=models/.docker/config.yaml api-server \
  python -m src.evaluation.run_all --split valid
```

기본 규모는 dev(상품 10,000·사용자 2,000·이벤트 200,000)다.
full은 상품 50,000·사용자 10,000·이벤트 1,000,000이며 dev와 별도 경로를 사용한다.

```bash
SCALE=full docker compose up --build -d
SCALE=full docker compose exec api-server python scripts/smoke_test.py --benchmark
```

기본 dev와 함께 full을 검증할 때는 별도 프로젝트·포트를 사용한다. B10 gate의
`mm-recsys-b10-full` 명령을 다시 실행하려면 다음과 같이 준비한다.

```bash
SCALE=full API_PORT=18000 DASHBOARD_PORT=18501 REDIS_PORT=16379 \
  docker compose -p mm-recsys-b10-full up --build -d
SCALE=full docker compose -p mm-recsys-b10-full exec api-server \
  python scripts/smoke_test.py --benchmark
```

이 경우 API·Streamlit은 각각 localhost:18000·localhost:18501이다.

full 평가 CLI의 `CONFIG_PATH`는 `models/full/.docker/config.yaml`이다.
모델 품질의 test 평가는 valid에서 선택·동결한 후 수행하며, smoke 성공만으로
full 품질이나 최종 제출 acceptance가 통과한 것으로 간주하지 않는다.
Docker 산출물에 C의 고정 평가 함수를 적용하고 Streamlit용 결과를 생성하는 B10 명령은 다음과 같다.
먼저 같은 규모의 `smoke_test.py --benchmark`가 통과해야 한다.

```bash
SCALE=full docker compose exec api-server python -m docker.quality --split valid
SCALE=full docker compose exec api-server python -m docker.quality --split test
SCALE=full docker compose exec api-server python -m docker.quality --split test --verify-existing
```

valid에서 데이터·모델·설정·평가 코드의 hash를 동결하고 test 전에 다시 검사한다.
품질 또는 지연 미달은 실패 종료한다. 원본 B/C 결과를 덮어쓰지 않고
`docs/results/docker/quality_full_{valid,test}.json`과 Docker runtime의 대시보드 파일을 만든다.
새 A/B 실험이 없으면 해당 탭은 미측정으로 유지한다. B11은 이 근거와 별도의 A/B·CT 근거를 집계한다.
오프라인 추천 품질은 B5 메모리 adapter를 사용한다. 현재 Redis store에는 추천기가 선택적으로
사용하는 `arm_statistics`·`record_exposures`가 없어 라이브 MAB 노출·보상 연결은 C의 보고서대로
`UNCONNECTED`다. Docker 기동·API·세션 검증은 이 연결의 완성을 뜻하지 않으며 INTEGRATE에서
담당 인터페이스를 보완해야 한다. [C의 인계 기록](docs/contributions/C.md)을 참고한다.

CT 자동 재학습은 기본 네 서비스와 분리된 선택 profile이다. API의 loopback 네트워크를
공유하므로 C의 내부 reload 접근 제한을 유지한다.

```bash
docker compose -f docker-compose.yml -f docker/compose.ct.yml --profile ct up --build -d
```

시뮬레이터의 합성 이벤트는 API 도착 시각으로 처리하고 체크포인트·이벤트 ID로 중복 적용을
방지한다. 진행 위치는 Redis 상태와 함께 저장하므로 새 Redis에서 이전 서버의 이벤트를
건너뛰지 않는다. 데이터 경로의 cursor JSON은 진단용 snapshot이다.
이 재생은 추천 노출에 귀속된 실제 사용자 반응이 아니므로 CTR·HitRate 개선의
근거로 사용하지 않는다. CT는 충분한 귀속 반응이 없으면 품질을 미측정으로 유지하고,
재학습해도 validation 개선 조건을 충족해야 새 모델을 채택한다.

데이터·모델·결과는 호스트의 `data/`, `models/`, `docs/results/`에 유지한다.
Hugging Face 캐시와 Redis 상태는 named volume에 유지하므로 첫 다운로드에는 네트워크가
필요하고, 이후 동일 캐시를 재사용한다. `docker compose down`은 컨테이너만 중지·제거한다.
볼륨을 지우는 `down -v`는 별도 승인 없이 실행하지 않는다.

API 메모리는 4GB·CPU는 4개로 제한하고 Streamlit·시뮬레이터는 각각 512MB로 제한한다.
권장 호스트는 RAM 16GB·CPU 4코어·여유 디스크 50GB, Docker 메모리 8GB 이상이다.
선택 CT 학습은 API와 별도로 최대 4GB를 사용하므로 추가 메모리 여유가 필요하다.
CPU Torch 2.6.0·torchvision 0.21.0을 로컬과 이미지에 공통 사용한다.
`docker.serve:app`은 `src.search.api:app`을 그대로 사용하며 두 서비스 factory의 로딩이 끝난 뒤
공유 프로세스의 Torch·FAISS 스레드를 통일한다. 추천 학습 스레드와
모델 가중치는 유지한다. 적용값은 runtime의 `serving_runtime.json`과 smoke에 기록한다.
Compose의 `SERVING_THREADS` 기본값은 valid에서 선택한 2다. 이를 지정하면 공유 추론
프로세스의 스레드만 바꿀 수 있으며 valid 요청으로 선택한다. Compose 밖에서는 미지정 시
`search.torch_threads`를 따른다. test 품질·정답·목표값을 바꾸지 않는다.
hybrid의 독립 텍스트·이미지 인코딩은 Docker adapter의 두 worker에서 병렬 실행한다.
기존 searcher 잠금으로 요청 간 인코딩을 직렬화하며 가중치·합성·검색은 원본을 사용한다.
어느 인코딩이 실패해도 둘 다 종료한 뒤 요청 이미지가 닫히도록 한다.
`SERVING_PARALLEL_HYBRID=0`으로 원래 순차 경로를 비교할 수 있다.
실제 CLIP valid 입력 12개의 벡터와 top10 비교는
[병렬 인코딩 검증](docs/results/docker/parallel_encoder_full.json)에 기록한다.
`SERVING_GC_FREEZE=1`은 모델 초기화 후 장수 객체를 반복 GC 스캔에서 분리한다.
임시 객체의 자동 GC는 유지하며 성공한 reload 뒤 수집·재등록하고 종료 시 해제한다.
full 진단에서 느린 요청 10개 모두 157~200ms의 세대 2 GC와 겹친 근거를 보존했다.
[Python의 freeze/unfreeze 정의](https://docs.python.org/3.11/library/gc.html#gc.freeze)를 사용하며
`SERVING_GC_FREEZE=0`으로 동일 조건의 진단을 재현할 수 있다.
`docker/constraints-*-py311-linux-arm64.txt`는 실제 Linux ARM64·Python 3.11 이미지에서
해결·검사한 의존성 제약이며 GPU 또는 다른 플랫폼에서 검증된 lock이 아니다.
다른 플랫폼은 해당 환경에서 다시 해결·검증해야 한다. Streamlit 이미지는 dashboard 의존성만
설치하며 torch·FAISS·transformers를 포함하지 않는다.

현재 Linux ARM64 CPU의 full 초기 v1.0 측정(모드당 warmup 10회·순차 HTTP 100회)에서는
text/image/hybrid/recommendation p95가 각각 27.447/178.894/173.203/106.317ms였다.
후보 검색 p95는 4.967ms·최소 300개, Redis 조회 p95는 0.250ms였다.
모델·인덱스는 메모리에 로드하고 응답 캐시는 사용하지 않았으며 ONNX는 적용하지 않았다.
CT 동시 학습이 없는 조건의 결과이고 부하·머신별 보장은 아니다.
[full 원시 측정](docs/results/docker/smoke_full.json)과
[검증 결과](docs/results/docker/verified_full.json)를 참고한다.

최초 준비 시간은 CPU·캐시·산출물 존재 여부에 따라 달라진다. 실제 실행별 시간과 재사용 여부는
`docs/results/docker/runtime/<scale>/preparation*.json`에 남는다. 새 클론의 dev/full 전체 생성부터
완료까지 걸리는 시간은 아직 미측정이며 CPU 학습·최초 CLIP 다운로드에 수 시간이 필요할 수 있다.

이번 Linux ARM64 CPU 환경(Docker 약 7.5GiB, API 4GiB·4 CPU)에서 측정한 준비 시간은 다음과 같다.

| 규모 | 처음 추천 모델을 학습한 준비 | 호환 산출물을 재사용한 준비 | 첫 실행의 기존 산출물 |
|---|---:|---:|---|
| dev | 439.820초 | 21.342초 | 데이터·검색 재사용, 빈 HF 캐시 다운로드 포함 |
| full | 2,698.698초 | 77.544초 | 데이터·검색·HF 캐시 재사용 |

full 첫 준비에는 별도 dev 진단과 학습 일시정지 시간이 포함된다. 이 값은 새 클론 전체 생성이나
다른 머신의 예상 시간으로 사용하지 않는다. 원본은
[dev 준비](docs/results/experiments/A/docker_first_preparation_dev.json),
[full 준비](docs/results/experiments/A/docker_first_preparation_full.json)에 보존했다.
재사용 시간의 원본도 [dev](docs/results/docker/preparation_reuse_dev.json),
[full](docs/results/docker/preparation_reuse_full.json)에 별도로 보존했다.

PDF 기준과 분석: [공유 데이터·평가 계약](docs/contracts.md), [원본 문제 분석](docs/setup_analysis.md).
최종 제출 저장소: https://github.com/k-pang-2026/mm-recsys
GitHub 계정은 사용자 미제공이므로 자동으로 실명과 연결하거나 다른 사람의 커밋을 꾸미지 않는다.
