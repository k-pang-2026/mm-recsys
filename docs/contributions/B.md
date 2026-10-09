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
