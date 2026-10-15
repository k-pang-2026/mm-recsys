# B 기여와 A·C 인계

2026-10-14 후속 B5: 기존 모델·원본87e5dac·PR8 9154479를 보존하고 공통 점수 정책/API/평가 상태를 정리했다.
full valid에서 CTR을 선택·동결한 뒤 한 정책만 test에서 평가했고 추천 품질과 B 주입 지연을 통과했다.
이전 실패·원본 기여 문서는 `docs/results/experiments/B/ranking_original_contributions.md`와
`ranking_pr8_contributions.md`에 보존했다. 현재 근거는 `ranking_metrics_v2.json`과 새 B5 gate다.
기본 C 서버/Redis/Docker·전체 회귀·원격 전달은 완료되지 않았다.

## A·C 인계 코멘트 — 모두 OPEN

### A-BATCH-001 / A / OPEN

- 원본 `.team/pending_publication.json`의 B4 SHA87e5dac를 삭제하거나 새 SHA 승인으로 재사용하지 않는다.
- 공통 helper에서 B4→B5 연속 로컬 커밋을 쌓고 최종 HEAD를 설명/승인/publish하는 경로를 보완한다.
- 이번 작업은 별도 클론에서 표준 helper로 B5를 한 번 커밋하므로 원본 대기를 건드리지 않는다. 공통 helper는 미수정이다.
- 검증: 게시 대기 보존, B4→B5 연속 commit, 역할/gate/변경 해시/승인 SHA 불일치 거부, 승인 전 push 금지.
- 추가 관측: 전체 pytest의 하위 프로세스 fork에서 OpenMP SHM Err179/SIGABRT 발생. 공통33검사는 단독으로 두 클론에서 통과했다.
  순서 변경만으로 전체 실패가 해결되지 않았다. 원시 로그 `ranking_regression_v2.json`/`experiments/B/*.txt`를 확인한다.

### A-HANDOFF-002 / A / OPEN

- `AGENTS.md`, `docs/codex_quickstart.md`, 역할 시작 절차에서 해당 담당 OPEN 코멘트를 읽고 현재 코드/의존성을 대조하도록 보완한다.
- A 시작은 A-BATCH-001/A-HANDOFF-002, C 시작은 아래3건을 확인한다. 발견/검토/적용/검증/commit을 구분한다.
- 현재 공통 안내 자동 연결은 미적용이다. B 소유 코드만 수정했고 외부 팀원에게 메시지를 발송하지 않았다.

### C-MAB-001 / C / OPEN

- 인터페이스: `record_exposures(user_id,product_ids)`, `arm_statistics()`, `arm_for(product_id)` 및 `update_reward(feedback)`.
- B `RecommendationFeatureStore`와 동등한 memory/Redis 구현을 제공한다. arm은 item/category, 통계는 exposures/reward다.
- 같은 사용자·상품의 최근 TTL1800초 노출에 클릭0.2/구매1.0, 노출 최대 보상, 중복 eventID, 미귀속 수를 적용한다.
- 재현: `OMP_NUM_THREADS=1 SCALE=full .venv/bin/python -m pytest -q tests/test_reranking.py`.
- 기대: 양 전략100건/4044완전탐색 및 보상·사용자 격리·TTL·중복·category arm 통과. B 어댑터는 PASS, 기본 C memory/Redis는 미적용/미검증.

### C-SESSION-002 / C / OPEN

- `src/serving/main.py:create_app`의 추천·event·feedback 세 경로에 같은 저장소를 연결한다. B factory는 `create_service(cfg,store)`다.
- 주입 예: `create_app(cfg,feature_store=RecommendationFeatureStore(cfg,products))`. 공통 서버/스키마는 B에서 변경하지 않았다.
- 재현: `OMP_NUM_THREADS=1 SCALE=full .venv/bin/python -m pytest -q tests/test_session.py tests/test_ranking.py tests/test_ranking_scoring.py`.
- 실제 full 증거: `ranking_latency_full_b5_v2.json:live_flow`의 클릭3회→관심/추천 변화, feedback 클릭→구매 최대1.0, 중복 미반영.
- B 주입 경로는 PASS. 기본 C store는 노출/arm 계약이 없어 MAB UNCONNECTED이며 Redis/Docker/TCP 통합을 통과로 표시하지 않는다.

### C-TEST-003 / C / OPEN

- `tests/test_serving_contract.py::test_unimplemented_models_never_report_empty_success`의 모델 없음 fixture를 빈 임시 data/model 경로와 격리한다.
- 실제 모델이 준비된 full 환경은200을 반환하는데 현재 공통 fixture는503을 요구한다. Redis 접속 의존 검사도 분리한다.
- B `tests/test_ranking.py`는 없음503/정상200/손상·해시불일치 시작 오류를 임시 bundle로 독립 검증했다.
- 전체 회귀 실패를 B 단독 통과로 숨기지 않았다. 두 전체 시도의 명령/원시 로그/exit1은 `ranking_regression_v2.json`에 보존한다.
- 기대: 모델 파일 유무와 무관한 fixture 결과, 정상/손상 검사 분리, memory/Redis 의존 검증 구분. 현재 C 적용은 미완료다.

## 현재 품질와 전달 경계

CTR 단독 full test HitRate0.698803/NDCG0.340204/Coverage0.419480, CTR AUC0.963370, 가능한 풀 위반0.
Coverage10000명/전체50000개, truth7686명이다. cold300명은 truth0이고 후보2313풀은 다양성 불가능했다.
30분 CVR 귀속·양성0/AUC미정의·기존에 조회한 test 사실을 유지한다.
B4/B5 ASGI p95는71.853/80.443ms. localhost bind Errno1 때문에 TCP는 UNMEASURED다.
전체 회귀는FAIL, 공통 통합은UNMEASURED. 추천 품질 PASS와 이 판정을 분리한다.

원격 PR8 병합 상태는 네트워크 실패로 미확인이다. 캐시의 이전 OPEN/Draft를 현재 상태로 취급하지 않는다.
원본 게시 대기는 유지하며 후속은 독립 클론의 한 B5 로컬 커밋/Draft 미리보기다.
PR8 병합/최신main 동기화 후 새 최종 SHA를 설명하고 명시 승인을 받은 뒤 새 PR로 전달한다.
