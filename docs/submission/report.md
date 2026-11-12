# 리팩터링 후 PDF 요구사항 재현 보고서

현재 소스에서 full valid를 동결한 뒤 test를 새로 실행해 **품질·지연 11개 기준을 모두 통과했다.**
상품 50,000개·사용자 10,000명·이벤트 1,000,000건, K=300, 정답·사용자 집합·기준은 유지했다.
최종 통합 판정은 [게시 직전 검사 결과](../results/experiments/A/final_validation_20261112/release/submission/checks.json)와 [최종 집계](../results/final_acceptance.json)를 따른다.
KST·소수 한 자리 표시의 전체 회귀·배포 소스 검증은 release 기록을, 아래 full 모델·품질 측정은 보존한 실행 기록을 따른다.
품질 통과와 A/B 개선, 실제 CT 승격, 원격 게시 여부를 구분한다.

## 데이터와 재현

- seed 42, 노출 2,254,172건, 시간순 train/valid/test 80/10/10, fixed-origin 평가.
- fingerprint: `2df9b64e07e3b2aad48c967c4c8d3d8b04883dd19279896bb374c4f9926ad7d8`.
- 새 빈 데이터·모델 경로에서 생성·감사·CLIP·FAISS·세 모델 학습·Redis 준비 6단계를 모두 통과했다.
  단계 실행 시간 합은 1651.5초이며, 독립 재생성의 기록 파일 8개는 원본과 해시가 같다.
- pinned CLIP 다운로드 캐시와 Docker 의존성 레이어는 재사용했다. 원격 새 클론 검증은 아니다.
- 최초 실행은 데이터·인덱스·학습 후 Redis 준비에서 timeout으로 실패했다.
  프로필 교체의 제한된 멱등 재시도를 추가한 뒤 새 빈 경로에서 전체 과정을 다시 검증했다.
  후속 회귀 검사에서 Redis 예외 import가 기본 ConnectionError를 가리는 문제도 수정했다.
  이 수정은 학습·데이터·준비 알고리즘을 바꾸지 않으며, 수정 후 실제 Redis·API와 전체 회귀·품질을 다시 검증했다.

근거: [빈 경로 재현](../results/experiments/A/final_validation_20261112/fresh_reproduction_full.json), [데이터 동일성](../results/experiments/A/final_validation_20261112/data_reproduction_full.json),
[최초 실패와 재검증 설명](../results/experiments/A/final_validation_20261112/verification_attempts.json).

## 품질과 속도

| 지표 | valid | test / 별도 benchmark | 기준 | 판정 |
|---|---:|---:|---:|---|
| mrr | 0.945000 | 0.925000 | ≥0.55 | PASS |
| ndcg_at_10 | 0.945000 | 0.925000 | ≥0.5 | PASS |
| recall_at_300 | 0.748963 | 0.745793 | ≥0.3 | PASS |
| auc | 0.966648 | 0.965785 | ≥0.7 | PASS |
| hit_rate_at_50 | 0.689281 | 0.665145 | ≥0.2 | PASS |
| ndcg_at_50 | 0.366957 | 0.329914 | ≥0.08 | PASS |
| coverage | 0.390440 | 0.374480 | ≥0.2 | PASS |
| search_p95_ms | 77.677496 | 77.677496 | ≤200 | PASS |
| recommend_p95_ms | 18.924133 | 18.924133 | ≤200 | PASS |
| candidate_p95_ms | 3.350916 | 3.350916 | ≤100 | PASS |
| feature_p95_ms | 0.245390 | 0.245390 | ≤10 | PASS |

Recall@300은 전체 카탈로그의 사용자별 미래 cart/purchase 정답에 대한 macro 평균이다.
Coverage는 고정 전체 10,000명의 Top-50 합집합/전체 50,000개다.
관측 cutoff와 train-only 학습을 유지하고 valid에서 선택한 설정으로 test를 한 번 평가했다.
BM25·인기도·Two Tower 등 기존 baseline과 비교 프로토콜도 유지했다.
AUC ≥0.70은 CTR 기준이다. CVR AUC는 별도 진단값이며 높은 구매 예측력을 주장하지 않는다.

지연은 aarch64 CPU의 단일 API 배포에서 10회 예열 후 100회 순차 요청으로 측정했다.
API 4GiB/4CPU, 추론 Torch/FAISS·OMP/MKL/OpenBLAS 2스레드, pinned FP32 CLIP 조건이다.
모든 측정 구간에서 simulator를 중지하고 다른 학습 컨테이너를 일시 정지했다가 복구했다.
Docker 전체 RAM은 약 11.66GiB였다. 다른 하드웨어와 동시 학습 중 지연으로 일반화하지 않는다.
검색 p95는 text 19.817ms, image 73.177ms, hybrid 77.677ms이며 최댓값으로 판정했다.

원본: [valid](../results/experiments/A/final_validation_20261112/quality_full_valid.json), [동결](../results/experiments/A/final_validation_20261112/quality_selection_full.json),
[test](../results/experiments/A/final_validation_20261112/quality_full_test.json), [HTTP 지연](../results/experiments/A/final_validation_20261112/smoke_full.json), [실행 조건](../results/experiments/A/final_validation_20261112/latency_conditions.json).

## 결과 예시와 한 명령 시연

실행 가이드는 [README](../../README.md)와 [재현 절차](reproduction.md)를 따른다.
`docker compose up --build -d` 후 `demo examples`로 검색·클릭·추천·A/B·CT를 실행한다.
이번에는 20명/군·2일로 전체 명령 연결을 확인하고, full 5,000명/군·30일 A/B를 별도 재측정했다.
기본 A/B 설정은 바꾸지 않았다. 상품·가격·점수·시간을 PDF의 참고 숫자로 고정 출력하지 않는다.
실제 한국어 텍스트·이미지·하이브리드 상품 의미, API 스키마, 422/413, 세션·Redis 귀속,
다양성·신규 상품·cold-start 및 브라우저 여섯 탭을 검증했다.

근거: [예시 의미](../results/experiments/A/final_validation_20261112/pdf_examples.json), [동료 평가](../results/experiments/A/final_validation_20261112/peer_review.json),
[HTTP·Redis](../results/experiments/A/final_validation_20261112/mab_full.json), [브라우저](../results/experiments/A/final_validation_20261112/browser_basic/browser.json),
[한 명령 시연](../results/experiments/A/final_validation_20261112/demo_examples_verified.json).
최종 집계 게시 후 화면 검증은 [browser_final](../results/experiments/A/final_validation_20261112/browser_final/browser.json)에 별도 기록한다.

## A/B 결과

| 지표 | Control | Treatment | 상대 변화 |
|---|---:|---:|---:|
| CTR | 25.0049% | 20.6625% | −17.37% |
| CVR | 1.2253% | 0.8857% | −27.72% |

각 군 5,000명·30일·top10, 150만 노출의 합성 실험이다.
CVR 차이 −0.339667%p, 사용자 군집 95% CI [−0.370099, −0.309234]%p, Z 검정 p=4.409705e−106이다.
통계 검산 PASS는 treatment 개선을 뜻하지 않는다.
고정 노출의 점수 순서인 오프라인 AUC와 각 정책이 생성한 새 노출의 A/B 반응은 평가 대상이 다르다.
원인별 ablation은 수행하지 않았으므로 음의 효과를 특정 단계 탓으로 단정하지 않는다.

이전 동일 데이터 실험과 사용자 배정·클릭·구매·통계는 같았다.
다만 treatment 노출 150만 건 중 1건의 상품 배분이 달라 완전 동일성 비교는 FAIL로 보존했다.
모든 상품 노출의 비트 단위 동등성을 주장하지 않는다.
근거: [통계 검산](../results/experiments/A/final_validation_20261112/ab_acceptance_full.json), [무손실 원본](../results/experiments/A/final_validation_20261112/ab_full_archive.json),
[동일성 비교의 실패 범위](../results/experiments/A/final_validation_20261112/ab_regression_detail.json).

## 실제 CT와 통제 시연

기존 배포 원장의 미처리 로그 **13,404건**으로 실제 재학습을 실행했다.
이번 학습은 `src.ct.retrain_trigger --train`의 1회 감시 호출이며 자동 worker가 직접 수행한 학습으로 표기하지 않는다.
기본 Compose의 자동 CT worker 기동과 공유 잠금 연결은 [별도 기록](../results/experiments/A/final_validation_20261112/automatic_ct_startup.txt)으로 확인했다.
후보 v1.2의 세 모델 학습·checkpoint 재로딩·동일 valid 평가는 모두 통과했다.
CTR AUC는 **0.966114654 → 0.966329962**, 개선 폭 **0.000215308**로 원래 최소 개선 0.001 미만이다.
따라서 **RETAINED**, 운영 v1.0 유지가 정상 판정이다. 중복 호출은 WAITING, 신규 로그 0건이었다.

재학습 스냅샷에는 누적 원장 이벤트 116,908건이 들어 있다.
원장 이벤트의 시간순 위치는 train 0, valid 5,372, test 111,536건이다.
이는 이번 트리거 13,404건의 분할 수가 아니다. 최신 로그를 임의로 train으로 옮기거나 CT test 정답을 열지 않았다.
새 snapshot cutoff에 따라 기존 base 이벤트가 train으로 이동할 수 있다.

운영 승격과 별개로, 동일한 실제 후보와 full 데이터·동일 guard를 사용한 별도 registry에서
초기 ranker를 상수 AUC 0.5로 두고 실제 승격·HTTP 모델 교체·롤백을 검증했다.
6개 HTTP 응답이 모두 200이며 운영 registry는 바뀌지 않았다.
통제 시연 PASS를 운영 모델의 개선·승격으로 해석하지 않는다.

기본 자동 CT는 로그 10,000건 또는 성숙한 활성 모델 성능 저하로 감지한다.
성숙한 train/valid 라벨이 부족하면 WAITING_FOR_LABELS로 대기하며 원래 시간순·귀속 조건을 지킨다.
입력·모델·설정이 같으면 불필요한 재시도를 억제하고, A/B와 CT는 공유 잠금으로 순차 실행한다.

근거: [실제 CT](../results/experiments/A/final_validation_20261112/ct_full.json), [학습](../results/experiments/A/final_validation_20261112/ct_training_sources_full.json),
[시간순 위치](../results/experiments/A/final_validation_20261112/ct_new_observation_folds.json), [분리된 라이프사이클 검증](../results/experiments/A/final_validation_20261112/ct_acceptance_full.json).

## 코드 품질과 범위

중복 데이터·모델 읽기, 불필요한 DataFrame 왕복과 전체 카탈로그 복사, CT 전체 로그 읽기를 줄였다.
재시도 상태·SQLite 시간 인덱스·선택 분할 라벨·공개 함수 타입을 보강했다.
상세 전후 측정은 [리팩터링 기록](../results/experiments/A/resource_refactor_20261112.md)에 보존한다.
전체 pytest·실제 Redis·mypy·의존성·공개 함수 검사와 근거 해시는 [최종 checker](../results/experiments/A/final_validation_20261112/release/submission/checks.json)가 판정한다.
이 문서만으로 미실행 검사를 PASS로 간주하지 않는다.

H&M·Retailrocket·DeepFashion은 [사용자가 전달한 강사 결정](dataset_scope.json)에 따른 추가 검증 범위이며 미획득이다.
실제 사용자 효과, 다른 하드웨어·GPU, 여러 배포의 동시 학습 용량, 외부 제출은 이번 검증 범위가 아니다.
기존 역할 기여·PR은 [원본](contributions.json)을 유지한다. 원격 게시·CI·병합은 GitHub PR 기록으로 별도 확인한다.
