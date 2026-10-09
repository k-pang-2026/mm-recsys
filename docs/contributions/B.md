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
