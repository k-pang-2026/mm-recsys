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
