# B — 추천 담당 기여

## B3a

- train-only feature encoding, 시점별 observed-history/구매 profile과 랜덤 negative 1:4 구현.
- metadata-only normalized Two Tower, sampled-softmax/AdamW 학습과 valid early stopping 구현.
- 전체 카탈로그 exact Recall@300, popularity/observed-history 기준과 cohort 진단 구현.
- train-only tiny-fit, 시점 누출·같은 timestamp·negative policy·ID mapping·PAD/norm·gradient·seed·bundle 검사 추가.
- C가 집계할 평가 결과와 models[/full]/v1.0 bundle 계약 정의.
- dev valid best epoch 8, Recall@300 0.819066. popularity 0.302853,
  observed-history category/brand/price 0.819390. 이력 기준 대비 소폭 미달을 유지해 보고.
- full frozen test 품질, ANN agreement, candidate p95 latency는 UNMEASURED.
- 검토 예정 역할 C. 실제 원격 리뷰/푸시/PR 생성 전 로컬 검증·커밋을 준비한다.

검증 근거: `docs/results/gates/B3a.json`, `docs/results/candidate_training_dev.json`,
`docs/results/candidate_dev_valid.json`, `docs/results/candidate_diagnostics_dev.json`.


## B3b

- 전체 카탈로그 normalized HNSW/IP bundle과 명시적 ID mapping/해시 검증 구현.
- 등록일/구매 제외 필터, -1/PAD/중복 제거, 부족한 후보 adaptive refill 구현.
- 동일 persisted 벡터의 IndexFlatIP/ANN agreement와 미래 정답 Recall을 분리해 평가.
- full 50,000/10,000/1,000,000 규모 학습, valid epoch7 선택·동결 후 최초 test 평가.
- full test ANN Recall@300 0.746281, agreement 0.999360,
  고유 후보 300개, 10 warm-up/100 serial CPU p95 1.369ms.
- 관측 이력 profile baseline 0.766795보다 낮은 결과도 보존.
- macOS ARM libomp 충돌 기록과 단일 스레드 추론 복구, 관련 회귀 테스트 추가.
- 원본 측정·선택·현재 bundle의 checksum을 대조하는 B3b verifier 구현.
- 후보 생성 단계 acceptance PASS, 전체 시스템 종합 acceptance UNMEASURED.
- 검토 예정 역할 C. 원격 동기화는 sandbox DNS 오류로 확인 불가하며 원격 push/PR 갱신 허가 전 상태다.

근거: `candidate_training_full.json`, `candidate_full_valid.json`, `candidate_full_test.json`,
`candidate_selection.json`, `candidate_diagnostics.json`, `candidate_benchmark_full_test.json`,
`candidate_metrics.json`, `candidate_runtime_failures.json`, `gates/B3b.json`.

## B4→B5 공통 변경 인계 (2026-10-13)

공통 파일은 B가 수정하지 않는다. 아래 OPEN은 인계 작성 상태이며 공통 적용 완료가 아니다.
독립 클론에는 자동 전달되지 않으므로 이 본문과 시작 지시문을 담당자에게 전달해야 한다.

### A-BATCH-001 / A / OPEN

- 현재: `scripts/step_git.py:main`은 `.team/pending_publication.json`에 다른 단계가 있으면 다음 단계 commit을 거부한다. 시작 시 pending은 없었으나 B4 helper commit `87e5dac5e5c42b07906dd53c85110cbdb1b66718` 생성 후 B5 commit이 exit1로 차단됨을 실제 재현했다. pending은 보존했다. 저장된 B3b state의 이전 SHA 승인을 새 HEAD에 재사용하지 않는다.
- 위치: `scripts/step_git.py:main`, `scripts/team.py`의 단계·게시 상태 처리.
- 요구: 검증된 소유 파일의 단계별 로컬 commit을 쌓고 마지막 정확한 HEAD만 게시 승인 대상으로 설명하는 batch 경로. 승인 전 push 금지, SHA 변경 시 재설명, 소유권·게이트 검증 유지. pending 상태 삭제나 helper 우회는 금지.
- 예: B4 gate→B4 local commit→B5 gate→B5 local commit→최종 HEAD 검토→명시 승인→publish.
- 테스트: 기존 게시 대기 보존, B4→B5 연속 commit, 승인 SHA 불일치 거부, push 금지, 역할 파일 위반 거부.
- 적용/commit: A 공통 보완은 미적용/없음. 실제 B4 helper 로컬 commit은 성공했다. B5 단계의 후속 commit은 B4 게시 대기를 보존한 상태에서 helper로 확인한다.

### A-HANDOFF-002 / A / OPEN

- 위치: `AGENTS.md`, `docs/codex_quickstart.md`, 역할 시작 안내.
- 요구: 시작 시 `docs/contributions/B.md`의 해당 담당 OPEN 인계 코멘트를 읽고 현재 코드와 대조. 발견·검토·적용·검증과 실제 commit을 구분해 기록.
- 테스트: A 시작은 A-BATCH-001/A-HANDOFF-002, C 시작은 아래 C 코멘트를 찾고 미적용 내용을 완료로 표시하지 않는다.
- 적용/commit: 미적용/없음.

### C-MAB-001 / C / OPEN

- 위치: `src/common/schemas.py:FeatureStore` 확장 검토, `src/serving/memory_store.py`, 향후 Redis FeatureStore.
- 요구: B의 `RecommendationFeatureStore` 계약처럼 `record_exposures(user_id, product_ids)`, `arm_statistics()` 제공. arm별 `exposures`, `reward`를 보존한다. `update_reward`는 동일 사용자·상품의 최근 TTL 내 노출에 귀속. 클릭 0.2/구매 1.0, 같은 노출은 최댓값으로 갱신, 중복 event ID 재적용 금지, 미귀속 수 집계. item/category arm 설정 지원.
- 예: `src.recommendation.feature_store.RecommendationFeatureStore(cfg, products)`를 공통 `create_app(..., feature_store=store)`에 주입. C는 동등 메모리·Redis 계약을 구현한다.
- 테스트: `tests/test_reranking.py`의 보상·TTL·중복·사용자 격리 계약을 메모리/Redis 모두에 적용.
- 적용/commit: B 어댑터 구현 예정; C 기본 연결 미적용/없음.

### C-SESSION-002 / C / OPEN

- 위치: `src/serving/main.py:create_app` lifespan과 기본 FeatureStore 선택, `/api/event`, `/api/feedback`, `/api/recommend`.
- 요구: 세 경로가 동일한 B 어댑터 또는 동등 저장소를 사용. B factory가 추천 노출을 저장한 뒤 실제 피드백에 반응해야 한다. 이벤트 3회 후 recent_clicks/interest와 추천 변화, 보상 후 arm 통계 변화 확인. B는 main을 수정하지 않는다.
- 테스트: `tests/test_session.py`의 공유 create_app 주입 경로와 동등 기본 서버/Redis 테스트, TTL·새 session_id 초기화.
- 적용/commit: 주입 테스트 구현 예정; 기본 서버 연결 미적용/없음.

### C-TEST-003 / C / OPEN

- 위치: `tests/test_serving_contract.py:test_unimplemented_models_never_report_empty_success`.
- 요구: 모델 없음 테스트에서 data/model 경로를 명시적으로 빈 임시 경로에 지정. 실제 로컬 학습 파일이 있어도 503 검사 안정적이어야 한다. 정상 모델=200, 손상/해시 불일치=시작 오류를 별도 검사.
- 테스트: B `tests/test_ranking.py` factory readiness 검사 참조; 공통 C 테스트를 산출물 유무와 분리.
- 적용/commit: 미적용/없음.

담당별 다음 시작 지시:

```text
A: A-BATCH-001, A-HANDOFF-002 인계 코멘트를 먼저 읽고 현재 코드와 대조한 뒤
A의 공통 범위에서 구현·검증해. B 추천 구현은 수정하지 말고 적용 결과와 commit을 보고해.
```

```text
C: C-MAB-001, C-SESSION-002, C-TEST-003과 B 어댑터 계약 테스트를 먼저 읽고
C의 서버·FeatureStore에서 연결해. 메모리·Redis 동등성과 실제 이벤트·피드백을 검증해.
```

### 인계 증거 갱신 (B 검증 후)

- C-MAB-001: B 어댑터와 item/category arm, 최근 동일 사용자·상품 노출의 reward max/중복/TTL/사용자 격리 계약 테스트를 구현·검증했다. C 적용은 OPEN.
- C-SESSION-002: full 학습 모델의 공유 API 주입 경로에서 클릭3회 후 관심·추천 변화 및 클릭→구매 reward0.2→1.0, 중복 미적용 확인. `docs/results/ranking_latency_full_b5.json:live_flow`에 실제 요청·응답 저장. 기본 C store/Redis 연결은 OPEN.
- C-TEST-003: `SCALE=full ... pytest -q tests/test_serving_contract.py::test_unimplemented_models_never_report_empty_success` exit1, 실제 준비된 추천 응답200인데 테스트가503을 요구함을 재현했다. 기본 dev 회귀는 B3a ANN 미준비를 구분한 뒤176개 통과했지만, 이것이 C fixture 격리 완료를 의미하지는 않는다. B의 임시 bundle 없음/정상/손상/준비된 index 누락 테스트는 독립적으로 통과했다.
- A-BATCH-001/A-HANDOFF-002: 공통 helper/안내는 직접 수정하지 않았으며 OPEN이다.

## B4·B5 최종 B 검증 (2026-10-14)

- DeepFM CTR/CVR 분리, train-only/시점 피처·30분 귀속·검열, 후보 일괄 점수화와 공유 factory/API 구현.
- full valid epoch11 선택·reload, test CTR AUC0.963370/LogLoss0.161054. 30분 CVR 양성0으로 AUC 미정의이며 한계를 공개했다.
- Epsilon-Greedy/UCB·cold-start·신상품·다양성·노출/보상 어댑터, GRU full epoch20 학습/reload 및0.3/0.7 fusion 구현.
- 두 전략 각각100건 무작위 검사, 독립 완전탐색4,044건, 실제 full 모델의 클릭3회 후 추천·관심 변화와 max reward/중복 검사 통과.
- 다양성 반례 수정 후 full 가능한 풀의 미충족0건. 전체10,000건 중2,313건은 후보 자체로 조건 달성 불가능하다고 진단했다. 초기2,333건 실패 원본도 보존했다.
- B5 full HitRate@50=0.048270/NDCG@50=0.011031은 목표 미달, Coverage=0.650540은 통과. Two Tower 기준선과 실패 수치를 보존하고 test를 보고 모델 재튜닝하지 않았다.
- API ASGI p95 B4=90.854ms/B5=93.591ms. 실제 TCP bind는 sandbox가 거부했으므로 TCP/curl/Redis/Docker acceptance는 미측정.
- 회귀180개 및 pip check 통과. 원본 B3b 모델·index·데이터·측정 해시 보존과 selection 재검증 통과.
- 새 후보는 범위 해시, legacy 후보는 검증한 원본 설정 스냅샷으로 ranking/session 설정과 분리한다.
- 공통 파일은 수정하지 않았다. 위 A/C 인계5건은 모두 OPEN이며 주입 검증을 기본 C 서버/Redis 통합 완료로 표시하지 않는다.
- 근거: `docs/results/ranking_metrics.json`, `ranking_full_test_b5.json`, `ranking_latency_full_b4.json`, `ranking_latency_full_b5.json`, `session_training_full.json`, `experiments/B/reranking_constraint_validation.json`.
