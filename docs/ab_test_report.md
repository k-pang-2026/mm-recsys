# A/B 합성 모의실험 보고서

최종 full 실험과 과거 dev 결과를 구별한다. 양 arm의 동일 반응 가설·seed42를 사용하며 test 행동과 잠재 선호를 추천기에 전달하지 않는다.
full 5000명/arm, 30일, top10; control=popularity, treatment=full_pipeline.
사용자 단위 무작위 배정, arm/사용자별 가변 상태·RNG 분리이며 불변 catalog만 공유한다.
CTR=clicks/impressions, CVR=purchases/impressions, 구매조건부 전환=purchases/clicks다.
노출 반복은 사용자 내부에 군집화한다. 한 번 이상 결과를 낸 사용자 비율의 Z/카이제곱은 별도 추정 대상이다.

| 항목 | control | treatment |
|---|---:|---:|
| users | 5000 | 5000 |
| impressions | 1500000 | 1500000 |
| clicks | 391237 | 298388 |
| purchases | 19890 | 12495 |
| explorations | 0 | 300000 |
| ctr | 0.26082466666666665 | 0.19892533333333334 |
| cvr | 0.01326 | 0.00833 |
| purchase_given_click | 0.05083874991373515 | 0.041875008378353014 |
| users_purchased | 4659 | 4167 |

| 지표 | 상대 lift | 차이 | 95% CI | 양측 p |
|---|---:|---:|---|---:|
| ctr (사용자 군집) | -0.23732162 | -0.06189933 | [-0.06363233909609962, -0.06016632757056698] | 0.0 |
| cvr (사용자 군집) | -0.37179487 | -0.00493000 | [-0.005244249985312268, -0.004615750014687729] | 1.2923115463602577e-207 |
| any_click (독립 사용자) | 0.0 | 0.0 | [0.0, 0.0] | 1.0 |
| any_purchase (독립 사용자) | -0.10560206052801024 | -0.09839999999999993 | [-0.11086984477360085, -0.08593015522639902] | 9.711701284429697e-53 |

음의 lift와 비유의 결과도 그대로 보존한다. 합성 가설의 모의 반응으로 실제 사용자의 인과 개선을 주장하지 않는다.
MAB는 B5 사용자별 메모리 adapter를 사용하며 별도 라이브 Redis 귀속 검증과 같은 실험이라고 주장하지 않는다.
full seeded 반복 실행은 미측정이다. 이번 원본의 배정·분모·집계·독립 사용자 통계·군집 CI는 C verifier로 재검산했다.
[full 무손실 원본](results/integration/ab_full_archive.json), [검산](results/integration/ab_verification_full.json),
[과거 C dev 원본](results/ab_test.json)을 보존한다. dev의 음의 lift를 full의 새 결과로 대체하지 않는다.
