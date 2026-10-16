# C 기여 기록

역할 C(박채영), 검토자 A(이제원). Git 작성자는 사용자가 지정한 chaezero03이다.
브랜치는 feat/C/platform이며 이번 범위는 B6 Redis Feature Store다.

## B6 변경

기존 공통 메모리 저장소와 같은 public interface를 제공하는 Redis backend와 factory를 추가했다.
API lifespan은 설정된 저장소를 선택하고 소유한 연결을 종료 시 정리한다.
최근 조회 LIST를 최대 50개로 제한하고 세션 HASH의 카운터·관심 카테고리·sliding TTL을 함께 갱신한다.
세션 ID 변경 시 조회 이력과 카운터를 초기화한다. 프로필 HASH는 세션 만료 후에도 남는다.
WATCH/MULTI로 이벤트·보상 중복 방지와 세션 갱신을 원자적으로 처리한다.
get_features는 한 번의 pipeline으로 일관된 스냅샷을 읽고 Redis 장애 시 경고와 빈 피처를 반환한다.

프로필 초기 적재는 1,000명 단위이며 잠재 persona와 미래 행동을 읽지 않는다.
C 소유 스트림 adapter가 공통 시뮬레이터의 parquet 청크를 소비하고 체크포인트·해시를 검증한다.
Redis 실패 시 체크포인트를 진행하지 않아 재시도가 가능하다.
API 테스트는 C 소유 pytest 지원 어댑터를 사용해 실제 Redis의 namespace를 테스트별로 격리한다. 이전 실행의 중복 방지 키나 만료 세션과 충돌하지 않는다.
CI workflow에 Redis 7 서비스와 localhost 환경, 실제 Redis 통합 검사 플래그를 추가했다. 원격 CI 실행 결과는 아직 미측정이다.
직접 의존성 추가/버전 변경은 없다.

## 실제 검증

- Python 3.12.10, CPU PyTorch 2.6.0, Redis Windows MSYS2 이식판 7.4.11을 사용했다.
- pip check 통과. 고정 CLIP revision의 텍스트/이미지 추론과 FAISS sanity 통과.
- seed 42의 dev 상품 10,000개·사용자 2,000명·이벤트 200,000개와 시간 분할 160,000/20,000/20,000을 검증했다.
- train/valid 진단에서 test outcomes를 읽지 않았다.
- 초기 전체 Windows 검사: 69 PASS/19 FAIL. B6 예외 이름 충돌 1개를 수정했다.
- Windows 실행 가능한 회귀 검사: 70 PASS. 공통 bootstrap 모듈의 POSIX /tmp 경로 관련 18개 검사는 BLOCKED다.
- B6 코드의 타입검사를 수행했다. 최종 검사 파일은 pytest 지원 어댑터를 포함한 6개다.
- 실제 Redis에 2,000명의 프로필을 적재했다. train 구간 스트림 2,100행 중 행동 이벤트 100개를 반영하고, 재실행 시 0개 추가 반영을 확인했다.
- 100명의 최대 길이 이력으로 10회 워밍업·100회 순차 호출을 측정했다. 목표 p95 10ms의 실제 수치와 원시 샘플은 latency 결과 파일을 따른다.
- Redis 장애 시 추천 200 검사는 공급된 테스트 추천 서비스를 사용했다. 실제 A/B 모델 경로의 장애 검증은 B5 병합 후 필요하다.

재현 명령은 [B6 실행 안내](../submission/b6_runbook.md)에 있다.
측정 근거는 [지연 결과](../results/latency/feature_dev.json),
[스트림 결과](../results/experiments/C/stream_dev.json),
[환경 검사](../results/experiments/C/bootstrap_environment.json),
[직접/전이 패키지 버전](../results/experiments/C/installed_packages.txt),
[train/valid 진단](../results/experiments/C/bootstrap_diagnostics_dev.json)에 저장했다.

## 제한과 다음 단계

B6 구조 검증과 전체 full acceptance를 구분한다. full 품질은 UNMEASURED이며 Docker 재현도 UNMEASURED다.
Windows build 19044와 RAM 약 8GiB 환경이므로 Windows 업데이트·WSL 2·Docker 준비와 충분한 메모리의 full 환경이 필요하다.
원격 푸시·PR 생성은 사용자의 해당 커밋 승인 후 수행한다. 이 단계의 PR은 Draft다.
다음 B7은 B5 추천 단계가 main에 병합되어 있어야 진행할 수 있다.

## 2026-10-15 새 macOS 기기 준비와 B7

역할 C(박채영), 검토자 A(이제원). 원격 C 브랜치 `7f6d922`를 추적하고,
PR #8까지 병합된 main `e5f1840`을 fast-forward로 반영했다.
fetch 대상을 main과 feat/C/platform으로 제한했으며 다른 역할의 미병합 브랜치는 가져오지 않았다.
PR #6의 B6와 PR #8의 B5 구조 gate가 main에서 PASS여서 B7을 진행했다.

macOS 26.6 arm64, RAM 24GiB, CPU 10코어에서 Python 3.11.17과 고정 의존성을 사용했다.
기본 Git/Python은 Xcode 도구 미설치로 실행되지 않아 저장소 바깥 `../.devtools/`에
Git·Python·GitHub CLI·Bash를 설치했다. 기본 Bash 3.2의 빈 배열/nounset 오류는
Bash 5.2.37로 해결했으며 공통 setup 스크립트를 수정하지 않았다.
공식 Apple Silicon Docker Desktop을 설치하고 Rosetta 시작 오류를 해소했다.
Docker 29.8.2, Compose 5.6.0, 엔진 메모리 약 8GiB와 healthy Redis 7.4.11을 확인했다.
GitHub CLI는 미인증이고 Codex CLI는 ChatGPT 로그인 상태다. 외부 푸시·PR 생성은 하지 않았다.

이 기기의 실행 진입점은 저장소 루트에서 `source .team/activate.sh`다.
이후 `bash setup_env.sh . --role=C`를 실행한다. 로컬 도구 경로, localhost 서비스,
실제 Redis 검사 및 C pytest 격리 플러그인이 적용된다. `.team/`은 커밋하지 않는다.
생략 옵션 없는 setup에서 pip check, 전체 검사, 데이터/이미지 검증, train/valid 진단,
고정 CLIP revision의 실제 양 모달 추론, Docker info와 Compose config가 통과했다.
setup 시점 242개 검사, 최종 B7 회귀 243개 검사가 통과했다.

seed 42 dev 데이터는 상품 10,000·사용자 2,000·이벤트 200,000개,
시간 분할 160,000/20,000/20,000이다. generation fingerprint
`3e1de868d26dc7c095f49d3841d98a944befd493937aa0ea3d0044e3062f889c`가 기존 B6와 일치했다.
`src.evaluation.ab_prepare`는 B 소유 trainer와 기존 config를 그대로 호출해
Two Tower·FAISS·DeepFM·세션 모델을 재생성한다. 파일·catalog·config·ID mapping·차원과
각 모델의 checksum, 실제 service load를 검사한다. 기존 비호환 산출물은 덮어쓰지 않는다.
학습은 train, 선택은 valid만 사용했다. 데이터·이미지·모델·CLIP 캐시는 모두 Git에서 제외된다.
B7에서 사용하지 않는 검색 임베딩·인덱스와 full 모델은 재생성하지 않았다.

B7은 설정 registry의 popularity 또는 Two Tower control과 B5 전체 pipeline treatment를 비교한다.
full 기본값 5,000명/군·30일을 유지하고 dev는 전체 사용자의 20%를 두 군에 나눈다.
이번 실행은 200명/군·30일·top10, 각 군 60,000회 노출이다.
persona의 카테고리 선호·가격 민감도·전환율과 위치 효과로 결과를 생성하며
treatment에 별도 가산점을 넣지 않는다. 추천기는 잠재 선호와 test outcomes를 읽지 않는다.
arm별 config·store·RNG·lock을 분리하고 사용자/날짜별 난수 stream을 고정했다.
사용자 간 적응 학습의 간섭을 막기 위해 MAB 피드백 상태도 사용자별로 분리했다.
초기 공용 bandit 실행은 독립성 가정에 맞지 않아 탐색 결과로 보존하고
`ab_initial_design_review.json`에 한계를 기록했다. 최종 gate에는 사용자별 분리 실행을 사용한다.

CTR=clicks/impressions, CVR=purchases/impressions이며 purchase/click도 별도 보고한다.
반복 노출을 독립 표본으로 세지 않고 사용자 cluster의 비율 차이·95% CI를 계산한다.
사용자별 한 번 이상 클릭/구매 여부에는 양측 Z와 Pearson chi-square를 적용하고,
빈도 부족 시 Fisher 검정과 점근 검정 한계를 표시한다. 모든 분모와 사용자별 집계를 저장한다.

실제 dev 결과는 control CTR 24.7833%, CVR 1.1517%, treatment CTR 19.8767%, CVR 0.9000%다.
treatment의 CVR 상대 lift는 **-21.8524%**, 차이는 -0.2517%p,
사용자 cluster 95% CI는 [-0.4043, -0.0991]%p, 양측 p=0.001228이다.
탐색 슬롯 비율은 control 0%, treatment 20%다. 이 수치는 합성 실험 결과이며
실제 서비스 우월성이나 full 최종 품질 통과를 뜻하지 않는다. 양의 lift는 B7 필수 gate가 아니다.
실제 Redis의 10회 워밍업·100회 순차 피처 조회 p95는 약 0.163ms로 10ms 목표를 통과했다.

재현·검증 명령:

```bash
source .team/activate.sh
OMP_NUM_THREADS=1 .venv/bin/python -m src.evaluation.ab_prepare
OMP_NUM_THREADS=1 .venv/bin/python -m src.evaluation.ab_test
OMP_NUM_THREADS=1 .venv/bin/python -m src.evaluation.ab_test --output .team/ab-repeat-dev.json
.venv/bin/python -m src.evaluation.verify_ab --repeat .team/ab-repeat-dev.json
.venv/bin/python -m pytest -q tests
```

[실험 결과](../results/ab_test.json), [모델 호환성](../results/experiments/C/ab_models_dev/compatibility.json),
[환경 검사](../results/experiments/C/macos_environment.json),
[기기 준비 근거](../results/experiments/C/macos_bootstrap.json),
[Redis 지연](../results/experiments/C/feature_macos_dev.json)을 저장했다.
동일 기기의 실제 반복 실행 비교는 B7 gate의 verify_ab 명령과 검증 JSON을 따른다.
다른 OS/Python에서는 동일 config/seed라도 부동소수점과 모델 바이트가 달라질 수 있어
기존 모델을 섞지 않고 로더의 호환성 검사를 통과한 새 bundle을 사용한다.
직접 의존성 추가는 없다. 전체 full acceptance와 전체 Compose 서비스 재현은 UNMEASURED다.
라이브 Redis의 MAB 노출/보상 연결은 이번 메모리 기반 실험과 구분하며 후속 통합에서 확인해야 한다.

B7 로컬 커밋은 설명과 명시 허가 후에만 푸시하고 Draft PR을 생성한다.
다음 담당 단계는 B8이며, 필요한 B2b는 이미 PR #3으로 main에 병합되어 있다.
C는 B9까지만 담당하고 B10 Docker와 B11 제출은 A에게 인계한다.

## B8 — 통합 평가와 대시보드 (2026-10-15)

역할 C(박채영), 검토자 A/B. PR #9의 두 common CI가 SUCCESS이고 PR이 MERGED인 것을
원격에서 확인했다. `scripts/team.py prepare C`로 최신 main `035b5dc`를 C 브랜치에
반영했다. B2b·B7 의존성은 충족됐으며 다른 역할의 미병합 기능 브랜치는 가져오지 않았다.

`src.evaluation.run_all`은 같은 데이터·모델·config로 검색, 후보, 분류, 최종 추천,
Redis와 실제 HTTP 지연을 측정한다. A/B 소유 모델·검색·학습 소스와 기존 결과 파일은
수정하지 않는다. 결과는 `docs/results/evaluation_<scale>_<split>.json`에 저장한다.
데이터·config·모델 manifest·소스 해시, 평가 fingerprint, 환경과 원시 지연 샘플을 포함한다.
지표마다 값·기준·PASS/FAIL/UNMEASURED와 valid/test/benchmark 구간을 기록한다.
dev/valid의 기준 통과와 full test 최종 acceptance를 구분한다.

검색은 고정된 독립 쿼리 200개/모드, 관측 가능한 relevance와 CLIP/BM25를 사용한다.
image-only BM25는 적용 불가이며 가짜 수치를 넣지 않는다. ANN/exact 벡터 일치율은
relevance 품질과 별도로 기록한다. efSearch/nprobe 진단은 valid에서만 수행하고
설정을 선택하거나 저장된 인덱스·test 정답을 바꾸지 않는다. 벡터 검색 p95는
인코딩·HTTP가 제외된 진단이며 API 지연 판정에는 실제 HTTP p95를 사용한다.
새 C 설정은 `serving.evaluation.nprobe_sweep: [1,4,8,16,32]`다.

필요한 dev 검색 임베딩과 세 인덱스를 동일 config/seed로 재생성했다.
상품 10,000개의 콘텐츠 중 텍스트 1,439개·이미지 256개만 실제 인코딩하고 나머지는
동일 콘텐츠 캐시를 사용했다. 고정 CLIP revision, 이미지·catalog·ID mapping·차원과
임베딩/인덱스 checksum을 실제 로더로 검사했다. 산출물은 `models/search/`에만 두고 커밋하지 않는다.
초기 macOS ARM 통합 평가가 종료 코드 139로 중단되어, 검색 인덱스를 로드한 뒤
B의 기존 단일 스레드 inference 정책을 C 평가에도 적용했다. 모델/검색 설정은 유지하고
실제 실행 스레드를 환경에 기록했다. 복구 근거는 `evaluation_runtime_recovery.json`에 있다.

후보 평가는 동일 벡터의 exact/ANN Recall@300, train-only popularity와 관측 이력 baseline을
포함한다. 최종 추천은 인기순·Two Tower·DeepFM·전체 파이프라인을 같은 사용자·truth에서 비교한다.
valid cutoff 이전 이력만 사용하고 미래 cart/purchase 고유 ID를 truth로 유지한다.
검색 불가능한 미래 상품도 truth에서 삭제하지 않는다. Coverage는 정답이 없는 사용자를
포함한 고정 2,000명의 top50 고유 상품/전체 10,000개 상품으로 계산한다.
CTR/CVR label 분모·양성 개수를 보고하며 단일 class CVR AUC는 미정의로 남긴다.

실제 dev/valid 품질 측정:

| 지표 | 측정값 | 기준 | 판정 |
|---|---:|---:|---|
| MRR | 0.928030 | ≥0.55 | PASS |
| NDCG@10 | 0.931912 | ≥0.50 | PASS |
| Recall@300 | 0.819066 | ≥0.30 | PASS |
| CTR AUC | 0.964822 | ≥0.70 | PASS |
| HitRate@50 | 0.839170 | ≥0.20 | PASS |
| NDCG@50 | 0.462911 | ≥0.08 | PASS |
| Coverage | 0.941100 | ≥0.20 | PASS |

검색 3개 모드와 추천은 실제 shared FastAPI·Redis·localhost TCP HTTP로 측정한다.
각 모드 10회 워밍업 후 100회 순차 요청이며 검색 판정에는 최악 모드의 p95를 쓴다.
후보와 Redis도 10회 워밍업·100회 순차 호출이다. 샘플·실제 p50/p95/p99·자원 배정은
통합 JSON을 따른다. 프로필이 비거나 Redis fallback인 호출로 지연 통과를 만들지 않는다.
benchmark용 Redis namespace와 서버를 정리하며 사용자의 컨테이너/볼륨을 초기화하지 않는다.

`evaluation_selection_<scale>.json`은 valid의 실행 조건과 불변 snapshot SHA를 기록한다.
명시적 `--split test`는 그 이후 data/model/config/source가 그대로일 때만 허용한다.
latency 갱신으로 화면 JSON을 다시 써도 과거 측정 snapshot은 보존한다.
이번 단계에서는 test 평가나 full 모델/데이터 생성·품질 튜닝을 수행하지 않았다.

대시보드는 검색·추천·A/B 실험·시스템 4개 탭, 5개 Plotly 차트와 기준선을 제공한다.
설정된 결과 디렉터리를 읽고 API_URL을 사용해 텍스트·이미지·하이브리드 검색과 사용자 추천을 호출한다.
기준 미달·결과 없음·단일 class·API 장애를 숨기지 않는다. A/B의 음의 lift도 그대로 표시한다.
실시간 health/ready와 저장된 성능 측정을 구분하고 CT 로그·측정 모델 버전을 보여 준다.
CT 기록이 없으면 B9 미측정으로 표시한다. `torch`/`faiss`를 import하지 않으며
기존 독립 대시보드 이미지의 직접 의존성만 사용한다. 결과 디렉터리에 쓰지 않는다.
Docker/Compose 정의·전체 서비스 컨테이너 성능 검증은 A B10 소유로 유지했다.

검증:

- 전체 회귀 검사 255개 통과. C 변경 8개 모듈의 타입 검사와 pip check 통과.
- Coverage 분모·미래 truth 유지·평가 freeze·누락/NaN·API 장애·readonly 결과 I/O를 검사했다.
- 별도 Python 프로세스에서 dashboard import 후 torch/faiss가 로드되지 않음을 확인했다.
- Streamlit 실제 서버 health/home HTTP 200과 AppTest의 4개 탭·5개 차트 렌더링을 확인했다.
- 11개 지표의 화면 값/판정이 JSON과 일치했다.
- 실제 API의 텍스트·이미지·하이브리드 검색 및 사용자 추천이 모두 200, 결과 10개를 반환했다.
- 실제 API를 연결한 AppTest에서 검색·추천 데모 폼도 예외 없이 실행했다.

재현:

```bash
source .team/activate.sh
OMP_NUM_THREADS=1 .venv/bin/python -m src.evaluation.run_all
.venv/bin/python -m uvicorn src.search.api:create_app --factory --host 127.0.0.1 --port 8000
# 별도 터미널, 동일 환경에서
.venv/bin/streamlit run dashboard/app.py --server.address 127.0.0.1 --server.port 8501
.venv/bin/python -m src.evaluation.verify_evaluation --dashboard-url http://127.0.0.1:8501
.venv/bin/python -m pytest -q tests
```

[통합 결과](../results/evaluation_dev_valid.json),
[검증·대시보드 근거](../results/experiments/C/evaluation_verification_dev_valid.json)를 참고한다.
직접 의존성 추가는 없다. 전체 full acceptance, CT, 전체 Compose 재현은 UNMEASURED다.
라이브 Redis MAB 노출·보상 attribution은 B5 adapter를 사용한 오프라인/B7 실험과 구분하며
여전히 UNCONNECTED로 공개한다. B8 로컬 커밋은 새 변경 설명과 명시 허가 후에만 푸시한다.
다음 C 담당 단계는 B9 Continuous Training이다.

## B9 — Continuous Training (2026-10-16, 박채영 C / 리뷰 담당 B)

B8 PR [#10](https://github.com/k-pang-2026/mm-recsys/pull/10)의 병합과 common CI 2개 성공을
확인하고, `origin/main`의 `32fdb7c`를 C 브랜치에 반영했다. 다른 역할의 미병합 브랜치는 가져오지 않았다.

`src/ct/`에 영속 SQLite 관측 journal, 주기 모니터, 이벤트 임계값 재학습, 버전 레지스트리와
롤백을 구현했다. 추천 요청의 `X-Recommendation-Request-ID` 응답 헤더를
`/api/event` 또는 `/api/feedback`에 그대로 보내면 사용자·상품·시간 창을 검증해 결과를 연결한다.
헤더 없는 이벤트는 고유 event_id로 재학습 수에는 포함하지만 CTR/HitRate의 양성으로 추정하지 않는다.
CTR은 성숙한 노출 상품 중 연결된 view 상품의 비율이다. HitRate@50은 성숙한 top_n=50 요청 중
연결된 cart/purchase가 있는 요청의 비율이며, top_n=10 요청이나 미성숙 관측은 그 분모에 넣지 않는다.
이 값은 온라인 감시 지표이며 B8의 고정 원점 오프라인 품질과 구분한다. 데이터가 없으면 null/UNMEASURED다.

기본 10,000개 새 이벤트 임계값은 공유 `ct.retrain_log_threshold`를 그대로 사용한다.
별도 파일 잠금으로 동시 재학습을 차단하고, 시작 시 잡은 watermark까지만 학습·소비한다.
학습 도중 들어온 이벤트는 다음 실행에 남고 실패 시 watermark를 진행하지 않는다.
관측 이벤트와 노출로 별도 경로에 새로운 시간순 8/1/1 분할을 만든 뒤 기존 B의 Two Tower,
FAISS, DeepFM, session 학습·로더를 seed 42로 사용한다. 기존 데이터·모델 및 최종 평가의 test를 덮어쓰지 않는다.
신규 snapshot의 test는 학습·선택에서 열지 않으며, 이전 관측 이력과 B8의 고정 test 평가는 별도로 유지한다.

`models/registry.json`에 버전·일시·부모·config/hash·검증 지표·상태를 보관한다.
초기 경로는 B의 `models/v1.0/` 그대로이며 후속 번들은 `models/v1.1/` 등에 저장한다.
B의 고정 v1.0 로더는 C adapter의 임시 디렉터리 뷰로 재사용해 B 코드를 변경하지 않았다.
기본 승격 기준은 같은 fresh valid cohort의 CTR AUC가 부모보다 **0.001 초과 개선**, AUC **0.70 이상**이다.
미측정·비유한 값·test 선택·미개선 후보는 승격하지 않고 기존 버전을 유지한다.
명시적 롤백은 실제 활성화 이력이 있는 조상 버전으로 제한한다.

`POST /api/admin/reload`는 직접 loopback 연결에서만 허용하며 전달된 HTTP 헤더를 신뢰하지 않는다.
등록된 활성 번들의 모델·index·특징 encoder·session 및 데이터 호환성을 모두 검사하고 warm-up한 뒤
단일 API 프로세스의 서비스 참조를 교체한다. 처리 중인 요청은 자신이 잡은 기존 참조로 완료한다.
카탈로그 변경은 검색과 함께 배포해야 하므로 단독 reload에서 거부한다.
FeatureStore는 같은 객체를 유지해 세션을 보존한다. 실패 시 현재 서비스를 유지한다.
대시보드는 현재 API 모델 버전과 저장된 측정 버전을 구분하고 중첩 CT 로그를 표시한다.

실제 검증 근거:

- [controlled fixture 결과](../results/ct_dev_fixture.json): 상품 400개·사용자 24명·원본 이벤트 6,000개,
  초기 5,000개 이후 실제 view/cart/purchase 727개를 추가 관측했다. 작은 fixture의 발동 임계값은 200이며 운영 기본값 10,000을 낮추지 않았다.
- 초기 fixture의 ranker만 의도적으로 상수 모델로 만들어 AUC 0.5000을 실제 측정했다.
  후보는 정상적으로 세 모델을 재학습했고 같은 valid cohort에서 AUC 0.9158, HitRate@50 0.9583을 측정했다.
  v1.0 → v1.1 승격·실제 HTTP reload, 개선 없는 v1.2 거부, v1.0 롤백을 검증했다.
  교체 중 추천 HTTP 요청 40개가 모두 200이었다. 이 개선율은 약한 초기 fixture와의 비교이며 실제 서비스 개선 근거가 아니다.
- 최초 4 epoch/1,024 batch 실험은 AUC 0.4110으로 승격이 거부됐다.
  [실패 근거](../results/experiments/C/ct_fixture_rejected_initial.json)를 보존하고 valid에서만
  20 epoch/128 batch로 학습을 조정했다. test나 정답·목표 기준은 바꾸지 않았다.
- 실제 세 학습 보고서와 lifecycle 로그를 `docs/results/experiments/C/ct_*_fixture.json`,
  `ct_fixture_log.jsonl`에 보존한다. `--verify-existing`이 보고서·로그·등록 번들의 실제 hash를 대조한다.
- [기존 dev 번들 호환성](../results/ct_bootstrap_dev.json): 기존 데이터 fingerprint
  `3e1de868d26dc7c095f49d3841d98a944befd493937aa0ea3d0044e3062f889c`와 모델을 그대로 등록·로드·warm-up했다.
  운영 dev 모델을 재학습하거나 fixture로 대체하지 않았다.
- [CT 활성화 후 실제 HTTP/Redis 측정](../results/ct_serving_dev.json)은 모드별 10 warm-up/100 serial 요청,
  CPU 1 thread로 수행했다. dev p95는 검색·추천 모두 기존 200ms 기준을 통과했다. 원시 표본과 환경을 결과에 보존한다.
- 최종 B9 gate의 9개 명령이 모두 종료 코드 0이다. 전체 회귀 검사 **274개 PASS**, 변경 모듈 **14개 mypy PASS**, pip check/compileall/diff 검사 PASS.
- 재학습 임계값·중복 차단·실패 복구·진행 중 이벤트 보존·승격/거부·손상 번들·롤백·reload 권한과
  기존 요청 완료·원본 데이터 보존·대시보드 CT 표기를 테스트했다. 최종 명령별 결과는 B9 gate에 기록한다.
- 최초 로컬 HTTP/Redis 실행은 sandbox의 소켓 제한으로 실패해 정상 실행 권한을 받아 재검증했다.

로컬 실행 및 A B10 인계 인터페이스:

```bash
# 일반 클론: source scripts/local_env.sh 와 .venv 활성화. 이 macOS 기기는 아래 기기별 runtime도 준비돼 있다.
source .team/activate.sh
.venv/bin/python -m src.ct.bootstrap
# 단일 API worker. CT profile/Compose 정의와 컨테이너 자원 검증은 A B10에서 구성한다.
.venv/bin/python -m uvicorn src.serving.main:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
# 별도 프로세스에서 60초마다 모니터. --train을 붙여야 임계값 기반 학습을 실행한다.
.venv/bin/python -m src.ct.retrain_trigger --watch --train --reload-url http://127.0.0.1:8000
# 명시적 이전 활성 버전 롤백 예시(실제 레지스트리에 해당 이력이 있을 때만 성공)
.venv/bin/python -m src.ct.retrain_trigger --rollback v1.0 --reason '운영 검증 후 롤백' --reload-url http://127.0.0.1:8000
# 전체 학습 번들을 별도 경로에 생성하는 B10용 CLI. 자동 승격하지 않는다.
.venv/bin/python scripts/train_all.py --data-dir data --work-dir models/.ct/manual-run-new
# 구조 재현: 매번 새 work-dir에서 실제 작은 학습·HTTP·승격·롤백 수행
OMP_NUM_THREADS=1 .venv/bin/python -m src.ct.verify_ct
.venv/bin/python -m src.ct.verify_ct --verify-existing
OMP_NUM_THREADS=1 .venv/bin/python -m src.ct.verify_serving
.venv/bin/python -m pytest -q tests
```

독립 CT worker와 API는 같은 로컬 models/results 볼륨을 사용한다. reload는 API의 직접 loopback에
호출해야 하며, 여러 API worker/분산 파일시스템의 원자 교체는 검증 범위 밖이다.
모델 파일은 불변으로 유지하고 새 버전을 등록한다. 카탈로그/사용자 schema 변경은 별도 migration이 필요하다.
누적 journal과 재학습 이력 정리 정책은 실제 운영 배포에서 별도 결정해야 한다.
직접 의존성 추가는 없다. Docker/Compose 파일·README·제출 문서는 담당 영역 밖이므로 변경하지 않았다.
full 규모 CT/최종 test 품질·전체 Compose 재현은 **UNMEASURED**다.
라이브 Redis MAB 노출·보상 학습 연결의 기존 **UNCONNECTED** 제한도 유지한다.
B9 로컬 커밋의 푸시·PR 준비 상태 전환은 변경 설명 후 새 명시 허가를 받아 수행한다.
C 담당 구현은 B9까지이며, PR 병합 후 다음 담당 단계는 A의 B10이다.
