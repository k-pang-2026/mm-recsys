# 실험·설계·최종 상태 보고서

수치는 B10 full test JSON에서 집계했다. 새 모델 학습이나 test 재평가를 수행한 결과가 아니다.
요구사항 페이지는 저장소의 [PDF 분석](../setup_analysis.md) 기준이며, 과제 예시 점수를 측정값으로 사용하지 않는다.

## 데이터와 평가 계약

- seed 42, generator 4.0.0, reference_time 2026-01-01 UTC.
- full: 상품 50,000·사용자 10,000·이벤트 1,000,000·노출 2,255,024.
- 시간순 train/valid/test 800,000/100,000/100,000. 동률 timestamp는 같은 split이다.
- valid cutoff: 2025-12-25T23:59:57.408+00:00; test cutoff: 2025-12-28T23:59:57.408+00:00.
- train으로 vocab/scaler/모델을 학습하고 valid로 epoch/정책을 선택했다. 동결 후 test를 평가했다.
- 데이터 식별자: `0973c4f2a7e7313f689bcdab0012d609cdf3e1eecb2d9f81e8fe90da541450c6`.
- 관측 카탈로그 전체에서 top300을 검색한다. 전체 상품 수와 cutoff 당시 가용 상품 수는 구별한다.
- test Recall truth 사용자 7,686명, 빈 truth 2,314명. 가용 카탈로그 48,872개, 미래 등록 truth 58개를 숨기지 않는다.
- Coverage는 고정 10,000명의 top50 고유 상품/전체 50,000개다. cold 300명은 test truth가 없어 HitRate를 측정할 수 없다.
- 설정·원본 파일 SHA·manifest·B10 runtime identity는 [config snapshot](config_snapshot.json)에 있다.

## 수식

- MRR@10 = 쿼리별 첫 relevant rank의 역수 평균; top10에 없으면 0.
- NDCG@K = mean(DCG@K/IDCG@K), DCG = Σ rel_i/log2(i+1), 이진 relevance.
- Recall@300 = mean_u(|Top300_u ∩ R_u|/|R_u|), R_u는 미래 cart/purchase 고유 상품 집합; 빈 truth 수를 별도 공개한다.
- HitRate@50 = truth가 있는 사용자 중 top50에 하나 이상 맞힌 비율. NDCG@50도 같은 미래 truth로 평가한다.
- Coverage = 고정 평가 사용자들의 top50 합집합 크기/전체 카탈로그 크기.
- AUC = 양성 점수가 음성보다 클 확률 + 동점 확률/2. 단일 class이면 미정의다.
- 상대 lift = measured/baseline − 1; baseline=0 또는 미측정이면 미정의다.
- CTR·CVR·사용자 단위 Z-test·군집 CI는 [A/B 보고서](../ab_test_report.md)에 분모와 함께 명시한다.

## full 목표와 실측

| 지표 | valid | test 또는 별도 benchmark | 기준 | 판정 |
|---|---:|---:|---:|---|
| mrr | 0.948333 | 0.931667 | ≥0.55 | PASS |
| ndcg_at_10 | 0.948333 | 0.931667 | ≥0.5 | PASS |
| recall_at_300 | 0.747050 | 0.750141 | ≥0.3 | PASS |
| auc | 0.971883 | 0.964767 | ≥0.7 | PASS |
| hit_rate_at_50 | 0.699833 | 0.700885 | ≥0.2 | PASS |
| ndcg_at_50 | 0.362061 | 0.342175 | ≥0.08 | PASS |
| coverage | 0.413780 | 0.415340 | ≥0.2 | PASS |
| search_p95_ms | 178.893950 | 178.893950 | ≤200 | PASS |
| recommend_p95_ms | 106.317129 | 106.317129 | ≤200 | PASS |
| candidate_p95_ms | 4.966624 | 4.966624 | ≤100 | PASS |
| feature_p95_ms | 0.249760 | 0.249760 | ≤10 | PASS |
| candidate_count | 300 | 300 | ≥300 | PASS |

p95 지연 행은 valid/test 품질 지표가 아니라 동일한 별도 benchmark 근거다. 모든 nominal 수치가 통과했다.
CPU ±50ms 안내를 기준 완화에 사용하지 않았다. [원본](../results/docker/quality_full_test.json),
[동결 valid](../results/docker/quality_full_valid.json), [원시 HTTP](../results/docker/smoke_full.json)를 참조한다.

## 검색 설계와 baseline

CLIP은 이미지와 텍스트를 대조 학습한 공통 벡터 공간으로 투영한다. 카탈로그 벡터를 미리 계산하고
질의 벡터를 정규화해 inner product로 검색한다. HNSW는 exact 대비 메모리·구축/검색 시간과 recall을 절충한다.
벡터 ANN/exact 일치율은 정답 relevance의 MRR이나 추천 Recall@300과 다른 지표다.
text/image/hybrid 각 200개 독립 query의 test MRR/NDCG는 0.940/0.880/0.975다.
text/hybrid BM25는 모두 1.0으로 CLIP 상대 lift는 −6.0%/−2.5%다. image-only BM25는 적용 불가다.
합성 속성 키워드가 정확히 일치하는 환경에서 BM25가 유리했으며 CLIP 우세라고 보고하지 않는다.
각 모드 ANN/exact top10 overlap은 1.0이지만 이는 벡터 검색 일치만 의미한다.
fusion/index 선택과 trade-off 실험은 [검색 보고서](../search_report.md)에 보존했다.

## 추천 설계와 baseline

Two Tower는 사용자 이력/프로필과 상품 속성을 벡터화하고 상품 벡터를 offline FAISS에 색인한다.
랜덤 negative 1:4는 학습용이며 평가 후보를 5개로 제한하지 않는다. DeepFM은 후보의 user/item/cross/context를
사용해 순위를 세밀하게 조정한다. 이후 다양성·신규 상품·탐색·세션 정책을 적용한다.
MAB는 노출과 귀속 보상으로 탐색/활용을 조절하지만 현재 live Redis adapter 연결은 UNCONNECTED다.
아래 full 품질은 B5 메모리 adapter의 고정 시점 평가다.

| 파이프라인 | HitRate@50 | NDCG@50 | Coverage |
|---|---:|---:|---:|
| train_popularity | 0.075072 | 0.016229 | 0.001000 |
| two_tower | 0.573510 | 0.186115 | 0.591380 |
| deepfm | 0.717278 | 0.388956 | 0.426920 |
| full_pipeline | 0.700885 | 0.342175 | 0.415340 |

| full pipeline 대비 기준 | HitRate 상대 lift | NDCG 상대 lift | Coverage 상대 lift |
|---|---:|---:|---:|
| train_popularity | 833.6222% | 2008.4133% | 41434.0000% |
| two_tower | 22.2096% | 83.8514% | -29.7677% |
| deepfm | -2.2855% | -12.0273% | -2.7125% |

후보 Recall@300은 ANN 0.750141, train popularity 0.234984, observed-history baseline 0.766795다.
ANN의 상대 lift는 각각 219.2313%, -2.1719%다.
DeepFM 대비 reranking의 품질 감소와 Coverage 감소를 그대로 공개한다. 다양성/탐색 제약을 적용하므로 모든 지표 개선을 보장하지 않는다.
CTR AUC 표본은 관측 노출 225,422개·양성 56,639개다. CVR은 clicked exposure 56,261개에 구매 양성 0개여서
AUC가 UNDEFINED_SINGLE_CLASS다. LogLoss 0.000011621은 CVR 예측력의 증거가 아니다.
CVR 라벨 분모(clicked exposure)는 A/B 보고서의 purchases/impressions 정의와 구분한다.
valid에서 선택한 CTR scoring, GRU 세션과 장기 선호 결합, 정책별 비교는 [추천 보고서](../recommend_report.md)를 따른다.

## 환경과 최적화

Linux ARM64 CPU, Docker Python 3.11, Torch 2.6.0+cpu, FAISS 1.9.0. 엔진 8 vCPU/약 7.5GiB,
API 한도 4GiB/4 CPU, 공유 추론 thread 2, 응답 캐시/ONNX 미사용, CT 동시 학습 없음.
각 모드 warmup 10회·순차 HTTP 100회. HTTP는 인코딩·피처·모델·검색·후처리와 왕복을 포함한다.
모델/색인은 메모리 적재 상태이며 Redis는 별도 실측했다. 후보 benchmark는 HTTP/Redis I/O를 제외한다.
full 환경 snapshot에는 swap 사용이 기록되어 있다. OOM 없이 한도 내 완료했지만 swap 0이라고 일반화하지 않는다.
초기 스레드/순차 hybrid 지연 미달과 GC 원인을 보존한 뒤 valid에서 병렬 인코딩과 GC freeze를 선택했다.
valid 12개 실제 CLIP 입력의 벡터 오차 0·top10 일치를 확인했다. 자동 GC는 유지한다.
[B10 보고서](../results/docker/report.md) 및 experiments/A의 실패/재검사 원본을 참조한다.

## 최종 상태

전역 타입/seed/상수 감사는 [감사 범위와 검토](audit_review.md)에 별도 공개한다.

수치 목표 11개와 후보 수는 B10 full test/benchmark 근거로 PASS다. 최종 전체 acceptance는 **UNMEASURED**다.
A/B의 dev 음의 lift, controlled CT fixture, 같은 버전 reload는 full 운영 완료와 구별한다.
fresh-clone 전체 생성·full A/B·full CT·live MAB·전역 타입 감사의 미완료와 P0 해석을
[제출 체크리스트](checklist.md)에 공개했다. 미측정을 FAIL/PASS로 바꾸지 않는다.
통합 시 모든 필수 check를 실제 실행하고 최종 C acceptance validator를 통과해야 한다.
