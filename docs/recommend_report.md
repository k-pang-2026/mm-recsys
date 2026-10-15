# B4 추천 API·B5 재랭킹·MAB·세션 최종 검증 v2

B 소유 구현과 B 메모리 주입 환경, 동결 CTR 정책의 full test 추천 품질은 **PASS**다.
공통 서버/Redis/Docker와 전체 회귀는 완료되지 않았으며 전체 acceptance는 **UNMEASURED**다.

## 점수 정책과 valid 선택

기존 DeepFM epoch11, GRU epoch20, Two Tower·HNSW와 데이터/피처 해시를 재사용했다. 재학습하지 않았다.
`recommend.scoring`은 학습 설정과 분리되어 모델/인덱스 재생성을 요구하지 않는다.
API와 평가가 `score_items` 및 `Recommender.rank_products/rerank_items`를 함께 사용한다.
지원 정책은 `ctr_cvr`(기존 곱 재현), `ctr`, `rank_fusion`이다. 결합 가중치0.25/0.50/0.75,
q(r)=(M-r)/(M-1), M=1이면1, M=0이면 빈 목록이다. CTR 동점은 상품ID로 안정 정렬하고
비유한/범위 밖 확률·중복 후보·잘못된 가중치를 거부한다.

5개 운영 정책과 비교 전용 Two Tower를 full valid에서 비교했다. 같은 후보와 예측값을 공유하고
각 정책의 노출 통계와 RNG를 독립시켰다. fixed-origin에는 세션 클릭/피드백이 없으므로
노출 TTL만 가상 시계로 만료시키고 누적 arm 통계는 유지했다. 이 시계는 실제 API/지연 측정에 사용하지 않는다.

| valid 정책 | HitRate@50 | NDCG@50 | Coverage | 가능한 풀 위반 |
|---|---:|---:|---:|---:|
| ctr_cvr | 0.040932 | 0.008253 | 0.644220 | 0 |
| ctr | 0.701506 | 0.360483 | 0.423360 | 0 |
| rank_fusion_0.25 | 0.559918 | 0.228130 | 0.522220 | 0 |
| rank_fusion_0.50 | 0.635474 | 0.274606 | 0.478280 | 0 |
| rank_fusion_0.75 | 0.691466 | 0.319329 | 0.439240 | 0 |
| two_tower | 0.568542 | 0.179561 | 0.613260 | 0 |

목표0.20/0.08/0.20와 가능한 풀 제약을 모두 충족한 운영 정책 중 최고 NDCG인 **CTR**을 선택·동결했다.
동률 기준은 HitRate→Coverage→실험 순번이며 Two Tower는 운영 선택에서 제외했다.
선택 기록은 `ranking_policy_selection_full.json`이며 모델/인덱스/피처·데이터·코드·난수·valid 집합 해시를 담는다.
API 설정도 CTR이다. Cold-start는 기존 인기·최근 상승량 정렬을 유지한다.

## 동결 후 full test

기존에 조회했던 test에서 동결 정책 하나만 평가했다. test를 보고 모델·가중치·정답·임계치를 다시 선택하지 않았다.
Coverage 사용자는 **10000명**, truth 사용자는 **7686명**, 분모는 전체 상품 **50000개**다.
정답은 같은 미래 구간의 고유 cart/purchase이며 빈 truth 사용자만 HitRate/NDCG 평균에서 제외하고 불가능한 truth는 유지한다.

| test 지표 | 기존 CTR×CVR+B5 | 동결 CTR+B5 | 목표 |
|---|---:|---:|---:|
| HitRate@50 | 0.048270 | 0.698803 | ≥0.20 |
| NDCG@50 | 0.011031 | 0.340204 | ≥0.08 |
| Coverage | 0.650540 | 0.419480 | ≥0.20 |

Two Tower test 기준선 HitRate/NDCG/Coverage는 0.569737/0.178922/0.617980다.
기존 실패 결과와 새 결과를 별도로 보존했다. 델타는 `ranking_policy_lift_v2.json`에 기록했다.
독립 CTR test AUC **0.963370**는 목표0.70을 통과한다.
**30분 CVR 귀속, 구매 양성0, CVR AUC 미정의**를 유지한다. 분류 수치는 동일 모델/피처/라벨의 기존 측정에서
해시로 검증해 재사용했으며 정책 비교 때문에 분류/학습을 반복하지 않았다.

동일 예측의 CTR×CVR 곱은 valid에서 추천 품질을 크게 떨어뜨렸다. CVR이 식별되지 않는 상태에서 곱을 쓰면
유용한 후보/CTR 순위를 바꾸는 것으로 ablation이 뒷받침한다. `ranking_policy_diagnosis_v2.json`에 관측과 추론을 구분했다.
valid/test cold 사용자300명은 truth가0명이라 cold 추천 품질을 판단하지 못한다.
valid2240/test2313개 후보 풀은 다양성 조건 자체가 불가능했다.
가능한 풀의 최종 위반은0이며 불가능한 풀의 반환ID와 카테고리 수·조건 진단 예시를 결과에 남겼다.

## API·재랭킹·보상 계약

공유 `GET /api/recommend`, `POST /api/event`, `POST /api/feedback`과 응답 필드를 유지한다.
모델은 lifespan 시작 때 한 번 로딩하고 피처→후보300→공통 점수→재랭킹→TopN을 수행한다.
모델 없음503/정상200/손상·해시불일치 시작 오류, 알려진·미등록 사용자와 TopN1~100을 검증했다.
`score`는 점수 정책의 정렬 점수다. CTR 모드는 CTR 확률, 곱 모드는 CTR×CVR, 결합은 순위 정규화 점수다.
Cold-start에서는 기존 인기·상승 점수로 대체되므로 reason을 함께 읽는다. 신상품/탐색/다양성 제약 때문에
최종 출력이 score 내림차순만 따르는 것은 아니다.

Cold-start<5, 최근 상승/인기, 가능한7일 이내 신상품≥1, 같은 범주 연속≤2, 중복 제거를 유지한다.
Epsilon-Greedy/UCB 각각100건 무작위 검사와 기존4044건 완전탐색 검사, item/category arm,
탐색 슬롯≤2와 표시를 검증했다. 동일 사용자·상품의 최근 노출 TTL1800초에 클릭0.2/구매1.0,
동일 노출 최대 보상, 중복 eventID, 사용자 격리와 미귀속 집계를 유지한다.
GRU0.3/장기0.7 결합도 그대로다. full 모델에서 클릭3회 후 관심·추천 변화와 피드백 상태 변화를
`ranking_latency_full_b5_v2.json:live_flow`에 저장했다. B 어댑터 주입 결과이며 기본 C store의 MAB는 OPEN이다.

## 지연과 환경

warmup10, 순차100, 동시성1, Top50을 고정하고 평가 종료 뒤 각 벤치를 순서대로 측정했다.

| p95(ms) | 내부 전체 | ASGI HTTP |
|---|---:|---:|
| B4 | 71.091 | 71.853 |
| B5 | 79.613 | 80.443 |

각 p95≤200ms, 오류0이다. p50/p99·단계별 지연·110건 원시 요청·대표 응답5개·CPU/스레드/패키지/
모델·정책 해시는 벤치 JSON에 있다. B4/B5 시작·모델 로딩은 각각13772.898/13828.109ms이며 요청 지연과 분리했다.
이는 공유 FastAPI에 B 저장소를 주입한 ASGI 왕복이다. 실제 TCP 벤치 앱/CLI도 구현했으나
localhost bind가 PermissionError Errno1로 거부되어 **TCP UNMEASURED**다. Redis/Docker 측정도 미완료다.
목표를 통과했으므로 추가 성능 최적화를 하지 않았으며 전후 속도 개선 비율은 주장하지 않는다.

## 회귀·인계·전달

B 검사는 gate에서 직접 실행한다. API/평가 일치, 동점·빈/단일 후보·비유한값, 모델1회 로딩,
품질 미달 CLI 실패 종료, 독립 CTR/candidate verifier·pip check·compile·diff 검사를 포함한다.
전체 회귀 첫 시도212통과/10실패/1skip, 공통 검사 우선 시도215통과/9실패/1skip으로 **전체 FAIL**이다.
실패는 C의 모델 없음 fixture와 OpenMP SHM 하위 프로세스 오류다. 공통33검사는 원본 PR8 클론과
후속 클론에서 단독 통과했지만 전체 통과를 대신하지 않는다. 정확한 원인은 공통 인계에서 추가 확인해야 한다.
원시 실패 로그와 명령은 `ranking_regression_v2.json` 및 `experiments/B/*.txt`에 보존했다.
커밋 전 gate 재기록의 독립 CTR/후보 검증2건도 OpenMP SHM Err179로 한 번 실패했다.
두 명령의 단독 재실행은 각각exit0이며 실패 gate/로그는 `experiments/B/ranking_gate_runtime_failure/`에 보존했다.
최종 gate는 표준 record_gate로 다시 실행한 실제 근거다.
A-BATCH-001/A-HANDOFF-002/C-MAB-001/C-SESSION-002/C-TEST-003은 모두 OPEN이다.

원본87e5dac의 게시 대기와 PR8 9154479의 오프라인 범위/head/title을 보존했다.
후속 클론은9154479 위의 B 소유 변경이며 공통 서버/스키마/C 저장소를 수정하지 않았다.
GitHub API 연결 실패로 PR8 현재 병합/최신main 동기화는 미검증이다. 한 번의 B5 로컬 커밋과 Draft 미리보기만
준비하고 실제 push/새 PR은 PR8 병합·최신main 확인 후 정확한 최종 SHA의 명시 승인으로 진행한다.
기존 SHA 승인을 재사용하지 않는다. 이번 B4 gate는 PR8 당시 오프라인 이력이고 API 증거는 새 B5 gate에 포함한다.

## 재현과 재개

저장된 full 평가를 응답 복구 목적으로 반복하지 않는다. 새 valid 비교는 별도 output/selection 경로에서 실행하며
동결 test 경로는 선택 기록·소스·모델·설정·임계치 일치를 요구한다. 세부 상태는 `ranking_followup_state.json`이다.

```bash
# 동일 환경의 기존 결과를 검증한다. 품질 미달이면 exit1.
OMP_NUM_THREADS=1 PYTHONHASHSEED=42 SCALE=full .venv/bin/python -m src.recommendation.verify_ranking --require-quality
OMP_NUM_THREADS=1 SCALE=full .venv/bin/python -m src.recommendation.verify_deepfm --metrics docs/results/ranking_classification_full_test.json
OMP_NUM_THREADS=1 SCALE=full .venv/bin/python -m src.recommendation.verify_candidate --metrics docs/results/candidate_metrics.json
# TCP bind가 가능한 호스트에서 새 output에 실제 측정한다.
OMP_NUM_THREADS=1 PYTHONHASHSEED=42 SCALE=full .venv/bin/python -m src.recommendation.bench_ranking --tcp --selection docs/results/ranking_policy_selection_full.json --output docs/results/ranking_tcp_full_b5_host.json
```
