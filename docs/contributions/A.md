# 이제원 (A, 팀장) — 공통 준비

사용자가 지정한 팀장 역할의 SHARED 준비를 Codex가 구현했다. 실제 Git 작성자 설정을
유지하며 다른 팀원의 기여/리뷰/계정을 만들지 않는다. 박정욱(B), 박채영(C)의 구현은 아직 시작 전이다.

- PDF·원본 프롬프트·환경 스크립트를 분석하고 B2 dependency/projection/index/relevance,
  B3 cutoff/truth/negative/signal/학습 진단과 full 지표 기준을 정리했다.
- 실제 공통 config·seed·metrics·타입/API 계약·메모리 FeatureStore를 구현했다.
- 재현 가능한 catalog/JPEG/users/Markov events/노출/split/manifest를 구현했다.
  나노초 시간값 오버플로를 실측 검사에서 찾아 수정했다. 이미지 content hash/동등 그룹도 저장한다.
- dev 10000/2000/200000 및 full 50000/10000/1000000 데이터를 생성하고 구조/시간 인과성을 확인했다.
  모델 평가와 분리한 train/valid history baseline으로 학습 신호를 확인했다.
- clone→setup→A/B/C branch→실행→검사→gate→로컬 commit→설명·허가→push 흐름과 중단 후 재개를 구현했다.
  full 최종 acceptance 수치/해시/실행 근거를 검사하는 최종 통합 제한을 추가했다.
- 실제 설치와 고정 CLIP text/image 추론, 회귀 검사 및 로컬 Git 원격의 병렬 분기/병합을 검증했다.
- 공통 준비·검색·추천·플랫폼·통합 모두 기능 브랜치→main PR로 제출하도록 수정했다.
  원격 푸시/PR 생성과 PR 병합의 승인을 분리하고 로컬 한국어 PR 미리보기, 기존 PR 갱신,
  Draft 전환, 정확한 승인 SHA·CI·리뷰 조건 검사를 구현했다. GitHub API 동작은 모의 검사로
  검증했다. 원격 PR/병합 실행 여부는 실제 발행 증거로 확인한다.
- Ubuntu 연동은 이미 활성화되어 있었지만 Docker Desktop이 종료되어 있던 원인을 확인했다.
  Desktop 시작 후 Docker/Compose 사전 검사, WSL 폴더 bind mount와 임시 Redis 컨테이너 PONG을
  검증했다. 생략 옵션 없는 setup 전체 실행도 통과했으며 `results/docker_wsl_verification.json`에
  실제 결과를 기록했다. 검색·추천 모델을 포함한 최종 4서비스 재현은 후속 단계에 남아 있다.

근거: [SHARED gate](../results/gates/SHARED.json),
[공통 준비 실측](../results/common_readiness.json),
[dev pilot](../results/data_diagnostics.json), [full pilot](../results/data_diagnostics_full.json).
공통 commit/push는 이 문서와 SHARED gate가 포함된 실제 Git 이력으로 확인한다.
검색/Two Tower/DeepFM/Redis/CT/Docker 완성 및 모델 최종 품질은 후속 담당 단계에 남아 있다.

- 사용자 최신 지시에 따라 충돌·원격 gate·CI·품질·필수 리뷰/보호 규칙을 확인한 PR은
  자동 병합하도록 구현했다. 푸시 전 설명·허가 규칙은 유지한다. 병합 직전 head/base SHA
  변경을 확인하고 CI 대기·차단 상태를 보존하며 같은 PR의 병합 재시도를 지원한다.

## B2a — 검색 인코더·산출물·인덱스 기반

이제원(A) 담당 단계의 구현·실행을 Codex가 수행했다. 지정 reviewer는 박정욱(B)이며
실제 팀원 리뷰가 수행됐다고 주장하지 않는다.

- 실제 고정 CLIP projected text/image 인코더, 공통 한국어 별칭, RGB/길이/FP32/norm 검증을 구현했다.
- 내용 기반 캐시, 완료 청크 해시 검증/중단 재개, 동시 쓰기 제한, 원자적 임베딩 발행을 구현했다.
- dev 10,000개 `(10000,512)` 양 모달 임베딩과 explicit IP의 text/image/hybrid HNSW를 생성했다.
- FAISS mapping·설정·해시 검증, -1 label 제외, save/load parity, IVFPQ 표본/차원 검사를 구현했다.
- BM25와 관측 속성 relevance/exact·ANN 진단을 추가하고 실제 query 전처리로 저장 벡터 재현을 확인했다.
- image/cross-modal ANN 일치율 미달과 일부 cross-modal 색 오검색을 숨기지 않고
  [검색 보고서](../search_report.md)에 남겼다. full 품질·API·지연은 B2b에서 측정한다.

근거: [B2a 실측](../results/search_b2a_dev.json), [환경 검사](../results/search_b2a_environment.json),
[B2a gate](../results/gates/B2a.json). 실제 로컬 커밋/푸시 상태는 Git 이력과 발행 증거로 확인한다.

## B2b — 검색 API·full 품질·HTTP 성능

- 전체 product ID를 보존하는 unique-vector HNSW membership과 cutoff 가용성 필터를 구현했다.
- 실제 입력을 인코딩하는 text/image/hybrid Searcher·SearchService factory와
  공통 FastAPI를 감싸는 JSON/multipart API 어댑터를 구현했다. C 소유 파일은 변경하지 않았다.
- 점수 측정 전에 valid/test 각 모드 200개의 독립 쿼리와 관측 속성 기반 multi-relevant 정답을 고정했다.
- valid에서 모드별 gallery·fusion·efSearch를 선택했다. full test 600개의 MRR/NDCG@10은
  0.931667이고 text/image/hybrid 모두 개별 기준을 통과했다. BM25가 더 높은 결과도 보존했다.
- 실제 CPU localhost HTTP로 각 모드 10 warm-up+100 serial 요청을 측정했다.
  hybrid p95 4-thread 276.784ms, 2-thread 206.986ms 미달을 보존하고 valid 요청으로
  1 thread를 선택했다. 최종 최대 모드 p95는 178.251ms다.
- 고정 test per-query, BM25/ANN, source hash, 개별 HTTP 지연, CPU 비교 및 단계별 gate를 남겼다.
  보고한 수치·코호트·모델/데이터·관측 p95 불일치를 최종 요약에서 차단한다.
- 로컬 모델 cache와 무관한 missing-model 계약 테스트, 실제 양 모달 fusion, JSON/multipart
  검증·lifespan 1회 로드·손상 산출물·동결 쿼리·membership·요약 검증 테스트를 추가했다.

근거: [검색 보고서](../search_report.md), [full 검색 결과](../results/search_metrics.json),
[B2b gate](../results/gates/B2b.json). 검색 단계 완료와 전체 추천/Docker 종합 완료는 구분한다.
지정 reviewer는 박정욱(B)이며 실제 리뷰·원격 B2b 푸시/병합 여부는 GitHub 증거로 확인한다.

## WORKFLOW v5 — Docker 역할 이관과 단계 인계 (이전 계약)

사용자 요청에 따라 Docker·컨테이너 성능 B10을 이제원(A)에게 이관했다.
README, Codex 가이드, 파일 소유권과 단계·PR·커밋 자동화를 함께 수정했다.
C의 B9 플랫폼 PR → A의 feat/A/docker B10 PR → C의 B11 제출 PR 순서를 적용해
미병합 기능 브랜치의 직접 공유와 상호 의존 대기를 방지했다.
Docker 준비·smoke·컨테이너 결과는 A가, Redis/서빙/평가/CT/제출 문서는 C가 담당한다.
README Docker 절차는 A B10, 최종 제출 문서는 B10 병합 후 C B11이 순서대로 작성한다.

독립된 로컬 Git 클론으로 B9/B10 미병합 차단, main 병합 후 Docker·제출·통합 브랜치
인계를 검증했다. 단계 소유권 거부, PR Draft 완료 시점과 별도 Docker 제목도 검사했다.
근거는 [WORKFLOW gate](../results/gates/WORKFLOW.json)의 실제 검사 결과다.
이번 변경은 역할·실행 계약 변경이며 Docker B10 구현·최종 재현이 완료됐다는 뜻은 아니다.


## WORKFLOW v6 — 제출 문서·검증을 팀장 A에게 통합

사용자 요청에 따라 C의 B11 제출 문서·제출 검사·final acceptance 집계를 A에게 이관했다.
C는 Redis·서빙·평가·대시보드·A/B·CT B6–B9를 담당하고, A는 B10 Docker 이후
feat/A/submission에서 B11을 수행한 뒤 feat/integration에서 최종 통합한다.
README, 가이드 두 사본, 역할·단계·브랜치·파일 소유권, 한국어 커밋·PR 자동화를 수정했다.
C의 평가 코드와 원본 A/B·평가·CT 측정은 보존하며 A B11이 이를 제출 자료로 집계한다.
이전 Docker 이관 검증은 [v5 gate 보존본](../results/experiments/A/workflow_docker_transfer_v5.json)에 남겼다.
현재 변경의 실제 검증은 [WORKFLOW gate](../results/gates/WORKFLOW.json)를 따른다.
B10/B11 구현이나 최종 full 품질 측정을 수행했다는 의미는 아니다.

README 다이어그램에도 A B10 → A B11 → A INTEGRATE의 담당과 순서를 반영했다.
다이어그램 보완 전 역할 이관 검증은 [v6 gate 보존본](../results/experiments/A/workflow_submission_transfer_v6.json)에 남겼다.

## B10 — Docker 준비·통합 실행과 CPU 성능 (2026-10-16)

원격 main `3ea2ee7`의 B2b·B5·B9 선행 gate를 확인한 뒤 `feat/A/docker`를 준비했다.
원본 산출물의 fingerprint와 해시 점검은
[입력 audit](../results/experiments/A/docker_input_audit.json)에 남겼다.
B2b 문서의 후속 변경은 이전 gate를 덮어쓰지 않고 이력으로 보존했다.
B/C의 모델·평가·서빙·CT 구현과 담당 overlay는 수정하지 않았다.

- 네 기본 서비스의 Compose·이미지·리소스·healthcheck·볼륨을 구성했다.
  API만 데이터 → CLIP 캐시/임베딩 → FAISS → Two Tower/DeepFM/세션 → Redis warmup을 준비한다.
  호환 산출물은 실제 checksum·모델 로딩으로 검증하고, stale/partial 데이터와 모델은 보존하며 중단한다.
- 준비 중 `/health=200`, `/ready=503`을 실제 HTTP로 확인했다.
  준비 완료 후 A의 JSON/multipart 앱과 C의 서빙·CT router를 그대로 사용한다.
  시뮬레이터는 readiness 이후 생성 없이 기존 이벤트를 API로 재생한다.
- Python 3.11 Linux ARM64 CPU 이미지의 실제 해석 결과로 transitive constraints를 고정했다.
  Torch 2.6.0+cpu·torchvision 0.21.0·FAISS 1.9.0 import와 pip check를 확인했다.
  dashboard에는 torch/FAISS/transformers가 없음을 실제 이미지에서 확인했다.
  이 제약을 다른 플랫폼이나 GPU용 lock으로 주장하지 않는다.
- 새 평가·CT 로그는 `docs/results/docker/runtime/<scale>`에 분리하고 mutable 결과는 Git에서 제외했다.
  smoke·준비·지연의 확정 snapshot만 기록한다. C의 평가 함수를 재사용하는 Docker 품질 CLI와
  원시 지연·데이터·모델·소스 해시를 재검사하는 verifier를 추가했다.
- 선택 CT profile은 `docker/compose.ct.yml`에 분리해 기본 네 서비스 계약을 유지했다.
  API loopback 공유로 내부 reload 제한을 유지하고, reload가 추론 스레드를 덮지 않도록
  Docker adapter에서 복원한다. 모델 가중치·학습 스레드·추천 정책은 변경하지 않는다.

실패와 수정도 보존했다. 처음 소켓 검사는 sandbox의 `PermissionError`로 실패해 정상 권한으로
재검증했다. 기존 모델·Docker용 Redis hostname이 암묵적 API 테스트에 섞인 실패는 프로젝트의
`src.serving.pytest_support`와 `scripts/local_env.sh`로 격리했다. 기본 네 서비스 검사 실패는
CT를 별도 profile 파일로 옮겨 해결했으며, 이후 전체 회귀 280개가 통과했다.
추가한 Docker 검사에는 준비 실패 전파·중복 writer 거부·부분 모델 보존·오프라인 CLIP 캐시·
실제 준비 HTTP·이벤트 재시도·원시 측정 변조 거부·reload 후 스레드 복원을 포함한다.
최종 검사 명령과 결과는 B10 gate를 따른다.

첫 dev 준비는 기존 데이터·검색 산출물을 재사용하고 빈 HF 캐시 다운로드와 추천 학습을 포함해
439.820초였다. 데이터 검증 3.12초, 캐시/임베딩 50.79초, 인덱스 1.27초,
추천 학습 377.55초, warmup 7.04초였다. 이는 완전한 clean-clone 생성 시간은 아니다.
[실제 첫 준비 기록](../results/experiments/A/docker_first_preparation_dev.json)을 보존했다.

처음 두 factory를 함께 로드하면 추천의 4-thread 설정이 검색 설정을 덮었다.
dev/valid HTTP p95는 image 211.013ms·hybrid 244.305ms로 실패했다.
공유 1 thread에서도 hybrid 211.082ms로 실패했고, 2 threads에서 text 30.073ms·image
177.947ms·hybrid 198.340ms·recommendation 33.492ms로 통과했다.
각각 10회 warmup·100회 순차 호출이며 이전 결과는 experiments/A의
`docker_latency_before_threads_dev.json`, `docker_latency_threads1_dev.json`에 보존했다.
수치 기준·test 정답·데이터는 바꾸지 않고 공유 추론 자원만 valid에서 선택했다.

후속 실제 reload 및 full 병행 학습 중에는 dev hybrid p95가 다시 229.728ms로 미달했다.
같은 resident 모델·2-thread 설정에서 별도 full 학습만 일시정지하면 181.428ms로 통과했고
학습을 즉시 재개했다. 최종 버전 고정 검사까지 포함한 반복 측정은 hybrid 196.802ms였다.
부하 조건·실패 샘플·중단/재개 상태는 experiments/A에 모두 남겼다. 이는 동시 CT 학습 중에도
항상 200ms를 보장한다는 뜻이 아니다. 고정 벤치마크는 CT worker가 없는 초기 v1.0 조건이다.

실제 dev 결과로 Streamlit AppTest의 네 탭·Plotly 그래프 4개를 예외 없이 렌더링했다.
dev의 초기 valid/test 품질 결과는 reload-budget 보완 전 소스의 역사적 측정이며,
기존 latency source의 원본 hash는 `docker_historical_dev_sources.json`에 연결해 보존했다.
최종 현재 소스의 full 품질 검증은 별도로 수행한다.

full 첫 준비는 기존 데이터·검색·HF 캐시를 재사용하고 추천 모델을 새로 학습해
2,698.698초가 걸렸다. 별도 dev 진단과 제어된 일시정지 시간이 포함된 실제 경과 시간이며,
추천 학습 단계는 2,649.71초였다. 완전한 새 클론 전체 생성 시간으로 해석하지 않는다.
[첫 full 준비](../results/experiments/A/docker_first_preparation_full.json)를 보존했다.

full 초기 추천 p95는 223.914ms로 미달했다. 실제 GC 시각과 요청 구간을 맞춘
[진단](../results/experiments/A/docker_gc_diagnosis_full.json)에서 느린 10개 요청 모두
세대 2 GC와 겹쳤다. Docker adapter에서 초기 모델 객체에 `gc.freeze()`를 적용하되
자동 GC는 유지하고 성공한 reload 뒤 수집·재등록하도록 했다. 이후 AnyIO 추론 worker에도
실제 Torch/FAISS 예산을 적용해 factory/reload의 OpenMP 설정 영향을 제거했다.
모델·정답·추천 정책·수치 기준은 변경하지 않았다.

병렬화 전 한 차례의 full HTTP 측정은 각 모드 warmup 10회·100회 순차 요청으로 통과했다.
text 33.986ms, image 164.382ms, hybrid 191.518ms, recommendation 99.102ms p95였다.
후보 p95 4.137ms·최소 300개, 실제 Redis p95 0.322ms도 통과했다.
[당시 측정 보존본](../results/experiments/A/docker_latency_before_type_guards_full.json)에
환경과 원시 요청을 남겼다.
고정 초기 v1.0·CT 학습 없는 조건이며 동시 학습 부하의 지연 보장은 아니다.

시뮬레이터 진행 위치를 Redis에 함께 저장하도록 보완해 새 Redis가 이전 backend의 이벤트를
건너뛰지 않게 했다. host cursor는 진단용 snapshot이며 fingerprint·offset·실패 재시도를 검사했다.
최종 전체 호스트 회귀 검사는 실제 Redis 포함 286개 통과, 실패·생략 0개였다.
[원본 pytest 출력](../results/docker/regression_host.txt)을 보존했다.

의존 모듈까지 포함한 정적 검사에서 Redis 전용 경로의 타입 확인 누락 세 곳을 보완했다.
중간 valid 평가는 6,000/10,000 사용자에서 중단하고 완료로 기록하지 않았다.
[중단 로그](../results/docker/quality_interrupted_full.txt)를 보존하고 최종 소스로 재평가 절차를 구성했다.
이후 순차 hybrid 반복 측정은 2 threads 211.622ms, 1 thread 262.744ms,
3 threads 245.829ms로 미달했다. 3-thread 비교 당시 CPU throttling·OOM·swap은 0이었고,
스레드 수만 변경하는 방식으로 안정적인 통과를 주장하지 않았다.

Docker adapter에서 독립 CLIP text/image tower를 두 worker로 병렬 실행했다.
기존 searcher 잠금·가중치·전처리·합성·FAISS·추천 정책은 보존하고
오류 시에도 두 작업을 종료한 뒤 요청 이미지를 닫도록 했다.
[실제 frozen valid 입력 12개 비교](../results/docker/parallel_encoder_full.json)의 최대 벡터
오차는 0이며 top10도 모두 일치했다. 병렬 실행·합성 일치와 오류 시 작업 종료를 회귀 검사에 추가했다.

최종 병렬 경로의 full HTTP p95는 text 27.447ms, image 178.894ms,
hybrid 173.203ms, recommendation 106.317ms로 모두 통과했다.
후보 검색 p95 4.967ms·최소 300개, 실제 Redis p95 0.250ms도 통과했다.
[현재 full smoke](../results/docker/smoke_full.json)와
[원시 표본·해시 검증](../results/docker/verified_full.json)에 실제 설정·원시 표본을 보존했다.

최종 공식 gate에서 실제 Redis 포함 전체 회귀 288개와 mypy 12개 파일·pip check·compile 검사가
통과했다. [최종 회귀 출력](../results/docker/regression_host_final.txt)을 보존했다.
최종 full valid의 11개 기준을 통과한 뒤 데이터·모델·설정·소스를 동결하고 full test를 실행했다.
test도 11개 기준이 모두 통과했다. Recall@300 0.750141, CTR AUC 0.964767,
HitRate@50 0.700885, NDCG@50 0.342175, Coverage 0.415340이었다.
최소 후보 300개와 가능한 후보 풀의 다양성 제약도 통과했으며 test는 설정 선택에 사용하지 않았다.

실제 full 결과로 Streamlit 네 탭·그래프 4개를 예외 없이 렌더링했다.
선택 CT profile의 현재 v1.0 loopback reload는 42.308초로 완료했고 이후 검색·추천도 정상 응답했다.
이는 같은 버전의 교체 동작 검증이며 실제 재학습·승격·운영 개선의 측정이 아니다.
기본 `docker compose up --build -d`도 최종 소스로 기동하고 실제 API·세션·대시보드를 검증했다.
요약과 원본 링크는 [B10 결과](../results/docker/report.md), 실제 명령·해시는
[B10 gate](../results/gates/B10.json)를 따른다. 최종 종합 acceptance는 `UNMEASURED`다.

미완성 인계도 숨기지 않는다. B 추천기는 `arm_statistics`·`record_exposures`가 없는 store에서
빈 bandit 통계를 사용하고 C Redis store는 이 두 인터페이스를 제공하지 않는다.
C B8의 `UNCONNECTED` 제한이 여전히 적용되므로 오프라인 B5 adapter 품질과 라이브 Redis MAB
학습을 구분한다. B10은 담당 소유권을 지켜 해당 B/C 코드를 수정하지 않았으며 INTEGRATE가
노출·보상 인터페이스를 보완해야 한다. 이 제한과 full A/B·최종 acceptance는 별개로 공개한다.

## B11 제출 문서·검사

B9/B10이 병합된 main e3af858에서 feat/A/submission을 준비했다. 검토 담당은 B/C다.
README에 실제 병합 PR을 연결한 3인 기여 표, 실행/문서 안내와 미완료 상태를 추가했다.
docs/submission에 요구사항→파일→검사→실측 대응표, 수식·baseline·환경·음의 lift,
설정/manifest snapshot, 새 클론/Compose/제출 절차와 체크리스트를 작성했다.
docs/ab_test_report.md는 C의 dev 원본 통계를 사용하고 반복 노출의 사용자 군집과
독립 구매 사용자 Z-test를 구별한다. P0 실제 데이터 해석은 UNRESOLVED다.

scripts/check_submission.py와 evidence helper는 필수 파일·모듈·ignore·타입/seed AST,
실제 mypy/pip/pytest, 라이브 API, 기여 PR과 원본 해시를 검사한다.
새 checker의 타입 검사와 13개 증거 변조/범위/경로/실패 상태 테스트를 확인했다.
전체 실행 결과는 docs/results/final_submission/checks.json 및 원시 로그에 보존한다.
B11 delivery와 final readiness를 구별하며 --require-ready는 미완료 시 종료 2다.
B10 full 측정 11개 수치와 후보 수를 동결/원시 표본과 대조해 final_acceptance.json에
source/sha256/split을 붙인다. 새 test 품질 실행이나 최종 acceptance PASS로 주장하지 않는다.

B/C 모델·서빙·평가 및 기존 원본 결과는 수정하지 않는다. live Redis MAB 연결, full A/B·CT,
clean-clone 전체 생성, 전역 타입 검사와 P0는 INTEGRATE/관련 담당에 인계한다.
기존 B9의 26개, B10의 78개 gate artifact hash를 구현 전에 대조했고 모두 일치했다.
GitHub public/익명 접근과 실제 PR #1–12를 읽기 전용으로 확인했다.
새 원격 clone의 초기 Redis 연결 실패와 복구 뒤 재검사를 구분해 보존한다.
B11 push/PR은 이번 로컬 commit 설명 후 새 명시 허가를 받아야 하며 INTEGRATE는 미수행이다.


## INTEGRATE — 현재 실행 기록

B11 PR [#13](https://github.com/k-pang-2026/mm-recsys/pull/13)의 승인된 head 64e16e7을
실제 원격 CI·보호 규칙과 대조한 뒤 main b40712a로 병합했다. feat/integration에서
Redis MAB 연결, 요청 피처 재사용, A/B 불변 메타데이터 공유, 전역 타입 보완을 수행했다.
YAML 정렬에 따른 생성 순서 결함을 수정하고 generator 4.1.0의 순서 포함 식별자를 적용했다.
빈 경로에서 full 데이터를 두 번 독립 생성해 모든 데이터 파일과 split의 checksum이 일치했다.
실제 전체 회귀 315개와 전역 mypy 120개 파일이 통과했다. P0는 사용자 전달 강사 지시에 따라
실제 데이터셋을 개발 후 추가 검증용으로 해석해 RESOLVED_OPTIONAL로 기록했다.

이 문단 시점에는 새 full 품질·HTTP 지연·5000명/arm A/B·full CT가 실행 중/미측정이다.
최종 결과와 범위는 [INTEGRATE 기록](../results/integration/report.md)을 따른다.
과거 B10/B11의 제한은 해당 실행 당시 기록으로 보존하며 이번 측정을 대신하지 않는다.

## INTEGRATE — full 실측과 최종 제출 검사

독립 빈 data/models에서 full 준비 2,725.892초, 데이터 두 번 hash 일치를 확인했다.
현재 추론 경로의 valid를 동결한 뒤 test의 원래 11개 수치 기준과 후보 수를 모두 통과했다.
full A/B 5,000명/arm·30일과 C 재검산을 완료했으며 음의 CTR/CVR lift도 보존했다.
CT는 실제 추가 HTTP 10,000건·세 모델 재학습·paired valid에서 RETAINED였다.
별도 full 초기 상수 ranker 기능 시나리오의 실제 승격·재로딩·롤백은 운영 개선과 구분한다.
최초 지연 실패·YAML 순서 결함·CT 메모리 실패와 재검사를 모두 보존했다.
최종 회귀 수·타입·pip·라이브 스키마·필수 여섯 판정은
[제출 검사 원본](../results/integration/submission/checks.json)과 pytest.xml을 따른다.
이 문서는 실제 팀원의 리뷰나 아직 승인하지 않은 INTEGRATE 원격 반영을 주장하지 않는다.

## WORKFLOW — Ponytail 연결과 전체 프로젝트 감사 (2026-10-17)

사용자의 명시 요청으로 공식 `DietrichGebert/ponytail` 커밋
`16352ac229eb08a9598dcae48fe9f2b342567d86`의 기본·감사 스킬을 `skills/`에 보관하고
출처·SHA-256·MIT 고지를 남겼다. 실제 지침 파일인 `AGENTS.md`에 읽기·적용 규칙을 연결했다.
독립 프로젝트 생성 시 링크가 깨지지 않도록 `setup_env.sh`의 복사 대상과 기존 복사 검증을 확장했다.
WORKFLOW의 소유 경로에 해당 파일을 추가했으며 역할별 서비스 소유권과 푸시 승인은 유지한다.

전체 프로젝트의 주요 실행·저장·학습·평가·배포·Git 흐름을 추적했다.
[감사 원본](../results/experiments/A/workflow_ponytail_audit_20261017.json)에 필수 6건·권장 2건,
최소 수정안과 영향, 검토 한계 및 [격리 재현 스크립트](../results/experiments/A/workflow_ponytail_probes.py)를 기록했다.
CVR 양성 0·다양성 불가능 후보 풀 2,738개·콜드 사용자 정답 0은 같은 날 앞선 main/Docker 실측과
원본 데이터로 확인했다. 해당 실측의 서비스 소스 해시는 현재 소스와 일치한다.
반복 클릭 학습 오류·저장 실패 응답·승격 뒤 reload 장애·과대 픽셀 이미지·헤더 예외를 격리 재현했다.
감사는 보고 전용으로 수행하여 발견한 서비스 결함의 수정이나 새 final acceptance를 주장하지 않는다.

전체 회귀는 실제 Redis를 사용해 336건 통과했다. 기본 서비스·대시보드·Docker 타입 검사도
116개 소스에서 통과했다. Git 자동화까지 넓힌 별도 타입 검사는 기존 두 파일에서 5개 오류를
찾았으며 원본 로그와 위치를 감사 보고서에 남겼다. 설치·복사와 관련된 집중 검증은 WORKFLOW gate를 따른다.
이전 WORKFLOW gate는 `workflow_before_ponytail_20261017.json`으로 보존했다.
변경은 `chore/team-workflow`의 로컬 커밋으로 준비하며, 원격 푸시·PR은 사용자 승인 전 수행하지 않는다.

## WORKFLOW — Ponytail 감사 후속 리팩터링 (2026-10-17)

사용자가 전체 감사·코드 최적화·리팩터링과 PR·병합을 명시 승인했다.
최신 `origin/main` b93c13f를 확인하고 기존 감사 커밋을 보존한 같은 브랜치에서 수행했다.
이번 전체 유지보수에 필요한 파일만 WORKFLOW 소유 경로에 명시했으며 다른 역할 브랜치를 합치지 않았다.

검색 입력은 픽셀·최대 변·비율을 먼저 제한하고 공유 FastAPI 검증을 한 번만 사용한다.
Redis 쓰기는 중복과 장애를 예외로 구분해 HTTP 503으로 연결한다. 시뮬레이터는 HTTP·체크포인트
장애 시 같은 배치를 재시도하며 저장 성공 후에만 위치를 옮긴다. 실시간 스트림도 공유 상태 플래그 대신
각 쓰기의 예외를 사용한다. CT는 미적용 활성 버전을 학습 전에 동기화하고 교체 실패를 재시도한다.
반복 클릭을 단일 CTR 정답으로 집계하되 구매 연결에는 마지막 원시 조회를 사용한다.

콜드 추천은 필요한 후보까지만 읽는다. 카테고리가 부족하면 후보 300개 안에서 보충하되
기본 ANN Recall@300·정답·시간 cutoff는 유지한다. 다양성 불가능·위반을 공통 품질 판정에 연결했다.
사용하지 않는 RerankStrategy 선언과 중복 이미지 검증을 제거하고 Git 도구의 타입 오류 5개도 해소했다.

생성기 4.2의 세션 간격과 사용자 유입을 수정하고 독립 full 데이터와 라벨을 검사했다.
구매 양성은 train 36,886 / valid 4,559 / test 3,513건이며 cold truth는 valid 7명 / test 5명이다.
최종 생성기에서 full 이벤트·노출을 다시 만들어 원본 parquet 해시가 일치했다.
별도 450상품·120사용자·12,000행에서 세 모델의 실제 학습·valid 선택·재로딩·API를 검증했다.
같은 독립 데이터로 Docker 4개 서비스, 3모드 검색·추천·세션·대시보드·보상·직렬 지연을 확인했다.
Redis 일시정지에서 503·동일 이벤트 재시도·중복 방지와 재생 위치 2,100→2,200의 자동 복구도 확인했다.

회귀·타입·실측 수치와 원본 실패/재검사 범위는
[감사 후속 원본](../results/experiments/A/workflow_ponytail_refactor_20261017.json)과 WORKFLOW gate를 따른다.
작은 학습의 CVR AUC가 정의되었다는 사실을 구매 예측 성능 개선으로 해석하지 않는다.
이 초기 검증 시점에는 새 full 모델의 품질·A/B·자연 CT 개선이 미측정이었다.
기존 데이터·모델·최종 판정은 덮어쓰지 않았으며 이전 WORKFLOW gate도 별도 파일로 보존했다.
원격 반영 결과는 실제 PR과 병합 SHA로 확인하며 실행 전 성공을 기록하지 않는다.

### 동일 결과를 유지하는 학습 경로 최적화

시각마다 작은 DataFrame을 만들던 두 전처리 경로를 정렬된 tuple 묶음 순회로 바꿨다.
학습 배치는 각 행을 꺼내 다시 쌓는 대신 인덱스 목록으로 한 번에 추출한다.
동시각 행동의 과거 이력, 모든 입력 Tensor·음성 샘플·섞기 순서·난수 상태가 이전 코드와 같다.
신규 회귀 2건을 포함한 전체 351개 테스트와 Python 133파일 타입 검사를 통과했다.

[3회 교대 측정 원본](../results/experiments/A/workflow_ponytail_efficiency_20261017.json)의 중앙값은
데이터 준비 3.506→0.329초(90.6% 감소), 세션 전처리 1.686→0.855초(49.3% 감소),
3 epoch 배치 로딩 0.182→0.048초(73.6% 감소)다. compact train 9,600행·학습 표본 6,939개,
CPU·Torch 4스레드, OMP/MKL/OpenBLAS 각 1스레드이며 같은 호스트의 full 학습과 병행했다.
전체 프로그램·full 학습·HTTP 속도 개선율로 확대 해석하지 않는다.
재현은 [비교 스크립트](../results/experiments/A/workflow_ponytail_efficiency.py)를 사용한다.
이미 다양성이 확보된 cold 후보 선택 사례의 ID 조회 50,000→600회 감소도 시간과 구분해 기록했다.

### 새 full 모델·Docker·동결 test 검증 완료

초기 미측정 범위를 후속 검증했다. 생성기 4.2 full 상품 50,000개·사용자 10,000명·행동
1,000,000행에서 세 모델을 실제 재학습하고 valid 최고 checkpoint를 저장·재로딩했다.
full Docker 4개 서비스와 현재 소스 113개 해시 일치, HTTP 검색 3모드·추천·세션·보상 검증을 통과했다.
warmup 10회·직렬 100회 HTTP p95는 텍스트 23.368 / 이미지 88.314 / 복합 93.428 /
추천 49.549ms다. 대시보드 HTTP·AppTest에서 4탭·11지표 JSON 일치와 검색·추천 폼을 확인했다.

valid 11/11 PASS 후 데이터·모델·설정·코드를 동결하고 test 11/11 PASS 및 재검산을 완료했다.
test Recall@300 0.737377(기준 0.30), CTR AUC 0.965100(0.70), HitRate@50 0.662995(0.20),
NDCG@50 0.323154(0.08), coverage 0.353880(0.20)이다. 제약 위반·다양성 불가능 후보 풀은
valid/test 모두 0건이다. 미래 상품·구매 상품 정책과 전체 카탈로그 분모·K·정답은 보존했다.
CVR AUC는 test 0.507732이며 계산 가능해진 사실을 구매 예측력 개선으로 주장하지 않는다.
cold truth valid 7명/test 5명의 작은 표본도 그대로 공개한다.

실측 원본·동결 identity·모델/소스 해시·중간 실패/재검사와 정확한 범위는 감사 후속 보고서에 기록했다.
새 full A/B·자연 CT·실사용 매출 효과와 대규모 동시 부하는 미측정이며
WORKFLOW `acceptance=UNMEASURED`를 유지한다. 수치 조건 통과를 최종 종합 acceptance와 구분한다.
