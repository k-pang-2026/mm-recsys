# A/B 합성 모의실험 보고서

## 2026-10-20 현재 full 데이터의 새 실험

생성기 4.2 데이터 `8b578e5c...`와 보존된 full 품질 평가의 동일 v1.0 모델을 사용했다.
각 군 5,000명, 30일, top10이며 control=popularity, treatment=full_pipeline이다.
각 군의 노출은 1,500,000건이다. 사용자 무작위 배정·반응 집계·군집 신뢰구간·
데이터/설정/소스 해시를 실제 실행 후 검증했다.

| 항목 | Control | Treatment |
|---|---:|---:|
| 클릭 | 377,500 | 307,112 |
| 구매 | 18,704 | 12,979 |
| CTR | 25.1667% | 20.4741% |
| CVR | 1.2469% | 0.8653% |

CVR 상대 변화는 **−30.61%**, 차이는 −0.3817%p이며 사용자 cluster 95% CI는
[−0.4124, −0.3509]%p, 양측 Z p-value는 9.76194e−131이다.
이 합성 반응 가설에서 treatment의 CVR이 낮았다. 통계/집계 검증 PASS는 성능 개선을
뜻하지 않는다. 이 결과로 정책을 바꾸거나 기존 test 정답·목표를 조정하지 않았다.
seed42의 이번 full 실행을 검증했으며 full 반복 실행 동등성은 별도로 측정하지 않았다.
실서비스의 전환 개선 효과를 측정한 결과로 해석하지 않는다.

실행 원본은 손실 없이 11개 통계 shard와
[archive](results/integration/20261020_full/ab_full_archive.json)에 보관했고,
[통계 검증](results/integration/20261020_full/ab_verification_full.json)과 원본 SHA를 연결했다.
실제 환경은 CPU Docker/Python 3.11.17/Torch 2.6.0+cpu, 모델 프로세스 Torch 4 threads다.
아래 이전 실험은 데이터/모델이 다른 과거 기록이다.

## 이전 full·dev 실험 보존

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
