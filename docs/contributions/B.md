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


## 1차 PR 범위 — B4 오프라인 CTR 분류까지 (2026-10-14)

사용자의 후속 지시에 따라 이번 PR은 B3b 후보 기준선을 보존하고 DeepFM 학습·test CTR AUC 검증까지만 포함한다.
B4 추천 서비스/API·주입 환경 지연, DeepFM 순위 품질, B5 재랭킹·MAB·세션·Coverage는 이 PR의 구현·통과 주장에 포함하지 않는다.
기존 B4/B5 통합 구현과 실패 측정은 원본 작업 공간에 보존했다. 해당 코드를 삭제하거나 성공으로 다시 표시한 것이 아니다.
이 단계는 부분 범위의 Draft이며 B4 전체/B5 완료, C B7의 선행조건 충족이나 전체 시스템 합격을 뜻하지 않는다.

- DeepFM full valid epoch11 선택 후 동결한 모델을 사용한다. full test CTR AUC 기존값은0.963370이며 독립 오프라인 평가로 다시 검증한다.
- 30분 귀속 정책은 사용자가 유지하도록 확정했다. CVR 구매 양성0으로 AUC가 미정의이며 전환 학습 성공으로 해석하지 않는다.
- CTR의 클릭 대리값은 연결된 view이고 생성기의 노출·view timestamp가 같은 한계가 있다.
- 추천 순위 품질은 이전 전체 실험에서 기준 미달이었다. 분류 AUC 통과를 추천 개선으로 해석하지 않는다. 이번 PR에서 품질 문제를 해결했다고 주장하지 않는다.
- B4/B5 API 연결과 지연은 제외한다. 기본 서버는 이 PR의 DeepFM을 자동으로 활성화하지 않는다.
- A/C의 공통 소스·설정·안내 파일과 테스트를 직접 수정하지 않는다. 아래는 실행 가능한 인계 계약이다.

## A·C 인계 코멘트 — 모두 OPEN

이 문서와 PR 본문에 코멘트를 포함한다. 별도 클론이나 다음 Codex 세션에 자동 전송·실행하는 기능은 없다.
담당자가 이 PR을 가져온 뒤 아래 시작 지시를 사용하고, A가 A-HANDOFF-002를 적용해야 공통 시작 절차에서 자동 발견할 수 있다.
코멘트 작성은 적용 완료가 아니다. 각 담당자는 발견 → 검토 → 적용 → 검증과 실제 commit을 기록한다.

### A-BATCH-001 / A / OPEN

- 현재/재현: 원본 작업 공간에서 B4 로컬 commit `87e5dac5e5c42b07906dd53c85110cbdb1b66718`이 게시 대기인 상태로 B5 commit helper를 실행하면 exit1, `another stage is awaiting push approval; finish that reviewed commit first`가 발생한다. 이번에는 사용자가 PR 범위를 축소하여 별도 검토 클론에서 B4만 준비한다. 원본 pending 삭제·helper 우회·B5 후속 commit은 하지 않았다.
- 위치/심볼: `scripts/step_git.py:main`, `scripts/team.py`의 단계·게시 상태 처리.
- 요구 동작: 검증한 역할 소유 파일의 단계별 로컬 commit을 쌓고 최종 정확한 HEAD만 게시 승인 대상으로 설명하는 batch 경로. 승인 전 push 금지, SHA 변경 시 설명/승인 확인, 소유권·gate 검증을 유지한다.
- 연결 예: B4 gate → B4 local commit → B5 gate → B5 local commit → 최종 HEAD 검토 → 명시 승인 → publish.
- 통과 검사: 기존 pending 보존, B4→B5 연속 commit, 승인 SHA 불일치 거부, 미승인 push 거부, 다른 역할 파일 거부.
- 적용 상태/commit: 미적용 / 없음. 이 PR은 공통 도구를 변경하지 않는다.

### A-HANDOFF-002 / A / OPEN

- 현재/재현: 현재 공통 시작 안내는 다른 클론의 B 인계 문서를 자동 전달하거나 A/C OPEN 코멘트 확인을 보장하지 않는다.
- 위치/심볼: `AGENTS.md`, `docs/codex_quickstart.md`, 역할 시작 안내와 필요 시 `scripts/team.py:prepare`.
- 요구 동작: 각 역할 시작 시 `docs/contributions/B.md`의 해당 담당 OPEN 코멘트를 읽고 현재 코드·의존성·적용 상태를 대조하도록 A가 공통 안내를 보완한다. 읽기만 한 항목을 완료로 표시하지 않는다.
- 연결 예: A 시작은 A-BATCH-001/A-HANDOFF-002, C 시작은 C-MAB-001/C-SESSION-002/C-TEST-003을 발견한다. 이 부분 PR에는 B5 어댑터·테스트가 없으므로 C의 B5 연결은 후속 구현을 먼저 확인한다.
- 통과 검사: 담당 OPEN 발견, 완료 항목 제외, 의존 구현이 없는 작업의 보류 표시, 적용·검증·commit 기록 구분.
- 적용 상태/commit: 미적용 / 없음. 자동 시작 연결은 아직 제공되지 않는다.

### C-MAB-001 / C / OPEN — 후속 B5 구현 의존

- 현재/재현: 이번 PR에는 B5 어댑터와 MAB 상태 갱신을 포함하지 않는다. B 소유 구현·계약 검사는 원본 B5 작업에 보존되어 있으며 해당 후속 PR이 제공되기 전에는 가져올 수 있다고 가정하지 않는다.
- 위치/심볼: `src/common/schemas.py:FeatureStore`, `src/serving/memory_store.py`, Redis FeatureStore, `update_reward`.
- 요구 인터페이스: `record_exposures(user_id, product_ids)`, `arm_statistics()`; arm별 `exposures`, 누적 `reward` 조회; item/category arm 지원.
- 보상 계약: 같은 사용자·상품의 최근 TTL(기본1800초) 내 노출에 귀속한다. 클릭0.2, 구매1.0이며 같은 노출은 최댓값만 반영한다. 중복 event ID는 재반영하지 않고 노출 없는 피드백은 미귀속으로 집계한다.
- 연결 예: 후속 B5의 `RecommendationFeatureStore(cfg, products)` 또는 동등 구현을 `create_app(..., feature_store=store)`에 주입한다. 메모리·Redis는 같은 계약을 구현한다.
- 통과 검사: 후속 `tests/test_reranking.py` 계약을 메모리·Redis에 적용. TTL, 중복, 사용자 격리, 클릭→구매 증분, 미귀속 집계, arm 전환을 확인한다.
- 적용 상태/commit: C 기본 연결 미적용 / 없음. B5 미포함 의존성 OPEN.

### C-SESSION-002 / C / OPEN — 후속 B4 API·B5 구현 의존

- 현재/재현: 이 PR은 오프라인 DeepFM 분류까지만 제공한다. 공유 API 주입 검사·GRU 세션·피드백 변화 검증은 원본 작업에 보존했으나 이번 PR의 적용 범위는 아니다.
- 위치/심볼: `src/serving/main.py:create_app` lifespan·기본 store 선택, `/api/event`, `/api/feedback`, `/api/recommend`.
- 요구 동작: 후속 B factory·어댑터가 준비되면 세 경로가 같은 FeatureStore를 사용한다. 추천 노출이 피드백 보상으로 이어져야 한다. 기존 기본 세션 기능의 존재와 MAB 연결 완료를 구분한다.
- 연결 예: 후속 B의 `create_service(cfg, store)`와 저장소 계약을 공통 기본 서버에 연결한다. C는 B 추천 소스를 직접 수정하기 전에 B 소유 경계를 확인한다.
- 통과 검사: 후속 `tests/test_session.py` 주입 흐름과 동등한 기본 서버·Redis 검사. 클릭3회 후 관심·추천 변화, 클릭→구매 reward0.2→1.0, 중복 무반영, 새 session_id와 TTL 초기화.
- 적용 상태/commit: 기본 서버·Redis 통합 미검증 / 없음. 후속 B 구현 의존성 OPEN.

### C-TEST-003 / C / OPEN

- 현재/재현: 원본 전체 구현 환경에서는 정상 모델이200을 반환하는데 `test_unimplemented_models_never_report_empty_success`가503을 요구하여 실패했다. 이번 부분 PR은 API factory가 없으므로 같은 실패가 반드시 발생한다고 주장하지 않는다.
- 위치/심볼: `tests/test_serving_contract.py:test_unimplemented_models_never_report_empty_success` 및 모델 준비상태 테스트.
- 요구 동작: 모델 없음 검사는 빈 임시 data/model 경로를 명시하여 실제 학습 파일 유무와 격리한다. 정상 모델200, 손상·해시 불일치 시작 오류를 별도로 검증한다.
- 연결 예: 이번 `train_deepfm.py:load_ranking`은 체크포인트·피처·설정·데이터 해시를 검증한다. API 상태 계약은 후속 B factory와 연결한다.
- 통과 검사: 로컬 모델이 있거나 없어도 같은 fixture 결과. 후속 정상/손상 bundle 검사와 full 회귀 통과. 현재503만으로 향후 정상 API까지 검증했다고 표시하지 않는다.
- 적용 상태/commit: 미적용 / 없음.

## 담당별 다음 시작 지시

```text
A: docs/contributions/B.md의 A-BATCH-001, A-HANDOFF-002 OPEN 코멘트를 먼저 읽고,
현재 코드와 대조한 뒤 A의 공통 범위에서 구현·검증해.
B의 추천 소스는 수정하지 말고 발견·검토·적용·검증 상태와 실제 commit을 보고해.
```

```text
C: docs/contributions/B.md의 C-MAB-001, C-SESSION-002, C-TEST-003 OPEN 코멘트를 먼저 읽고,
현재 코드와 후속 B4 API/B5 구현의 실제 제공 여부를 확인해.
이번 부분 PR에 없는 어댑터·테스트가 있다고 가정하지 말고 의존 작업은 보류해.
C 소유 서버·저장소·테스트에서 가능한 항목을 구현·검증하고 적용 상태와 commit을 보고해.
```


### 이번 부분 PR의 실측 갱신

- 독립 full test 분류 재평가: CTR AUC0.9633700394/LogLoss0.161054131 재현. CVR AUC 미정의 유지.
- 후보 verifier와 원본 모델·인덱스·데이터·측정 해시 보존 검사 통과.
- 최신 로컬 origin/main 캐시에는 C의 Redis 기본 저장소가 이미 있다. 노출 귀속·MAB 계약까지 적용됐다는 뜻은 아니다.
- 이 검토 클론에서 전체 회귀는191통과/1실패/1skip이다. 실패는 기본 Redis(redis:6379) 접속 불가로 C의 기존 API fixture recent_clicks가 빈 값인 경우다. 공식 CI plugin을 붙인 검사도 같은 결과다.
- C-TEST-003/C-SESSION-002 추가 근거: 이번에는 모델 준비상태503 검사를 통과한 뒤 Redis 의존 검사에서 실패한다. 모델 상태 격리와 Redis fixture/연결 검사를 각각 확인해야 한다.
- 실패 기록은 `docs/results/ranking_ctr_regression_limits.json`에 보존했다. 이 상태를 전체 CI 통과라고 표시하지 않는다.
