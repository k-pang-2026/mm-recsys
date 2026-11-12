# 최종 통합 실험·설계 보고서

2026-10-20 생성기 4.2 재통합은 [현재 실행 기록](../results/integration/20261020_full/report.md)을
따른다. 기존 full 평가 보존·빈 경로 재현·새 A/B와 실제 CT 학습·비교를 확인했다.
자연 CT는 CTR AUC 0.965535→0.965946으로 개선됐지만 원래 최소 개선 0.001에 미달해
기존 모델을 유지했다. 별도 full 크기 초기 fixture의 실제 교체·HTTP 재로딩·롤백은
통과했다. A/B CVR 상대 변화 −30.61%와 OOM·Docker 복구 기록을 보존하며 운영 개선으로
주장하지 않는다. 현재 데이터의 최종 판정·전체 회귀·타입 검사는
[이번 제출 검사 원본](../results/integration/20261020_full/submission/checks.json)을 따른다.
아래는 생성기 4.1의 이전 통합 기록이다.

이 보고서는 INTEGRATE의 실제 full 실행 결과를 집계한다. 원본 B/C/B10/B11 결과와 최초 실패는 보존했다.
원격 main b40712a(B11 PR #13) clone 위 현재 통합 변경을 적용한 독립 경로에서 검증했다.
기능 브랜치의 원격 반영 상태는 Git 이력과 PR로 확인하며, 아래 값은 명시된 실행 시점의 snapshot이다.

## 데이터와 평가 계약

- seed 42, generator 4.1.0, reference_time 2026-01-01T00:00:00Z.
- full counts: {'products': 50000, 'users': 10000, 'events': 1000000, 'impressions': 2255024}.
- split counts: {'train': 800000, 'valid': 100000, 'test': 100000}.
- data fingerprint: `6cbd02ebd828afc464e02bc95edd25c80f96175f2f14f53af707edcba3665ae9`.
- 전체 카탈로그에서 macro-user Recall@300, 미래 cart/purchase 고유 truth, 고정 10,000명의 top50 Coverage를 사용한다.
- train-only fitting, valid 선택·동결 후 test 재검증이며 K·기준·분모·정답을 바꾸지 않았다.
- 4.1.0의 올바른 생성 순서는 B10의 원래 올바른 데이터와 같다. 이 test는 과거 관측 이력이 있으며 신규 미관측 holdout으로 주장하지 않는다.
- H&M·Retailrocket·DeepFashion은 사용자 전달 강사 지시에 따라 개발 후 추가 검증용이다. [결정](dataset_scope.json)은 RESOLVED_OPTIONAL이다.

## 수식

MRR@10은 첫 relevant rank의 역수 평균, NDCG@K는 쿼리/사용자별 DCG/IDCG의 평균이다.
Recall@300은 `mean_u(|Top300_u ∩ R_u|/|R_u|)`이며 빈 truth 수를 별도 보고한다.
HitRate@50은 truth 사용자 중 적중 비율, Coverage는 고정 평가 대상 top50 합집합/전체 카탈로그다.
AUC는 양성-음성 순위 확률이며 단일 class에서는 정의되지 않는다. 상대 lift는 `measured/baseline - 1`이다.
CTR/CVR 분모와 사용자 군집 CI는 [A/B 보고서](../ab_test_report.md)를 따른다.

## full 목표와 실측

| 지표 | valid | test 또는 benchmark | 기준 | 판정 |
|---|---:|---:|---:|---|
| mrr | 0.948333 | 0.931667 | ≥0.55 | PASS |
| ndcg_at_10 | 0.948333 | 0.931667 | ≥0.5 | PASS |
| recall_at_300 | 0.747050 | 0.750141 | ≥0.3 | PASS |
| auc | 0.971883 | 0.964767 | ≥0.7 | PASS |
| hit_rate_at_50 | 0.699833 | 0.700885 | ≥0.2 | PASS |
| ndcg_at_50 | 0.362061 | 0.342175 | ≥0.08 | PASS |
| coverage | 0.413780 | 0.415340 | ≥0.2 | PASS |
| search_p95_ms | 123.495639 | 123.495639 | ≤200 | PASS |
| recommend_p95_ms | 54.322763 | 54.322763 | ≤200 | PASS |
| candidate_p95_ms | 6.821933 | 6.821933 | ≤100 | PASS |
| feature_p95_ms | 0.394422 | 0.394422 | ≤10 | PASS |
| candidate_count | ≥300 | 300 | ≥300 | PASS |

지연은 품질 test 지표가 아닌 별도 benchmark다. CPU 오차 안내를 기준 완화에 사용하지 않았다.
[test 원본](../results/integration/quality_full_test.json), [valid 동결](../results/integration/quality_selection_full.json),
[원시 HTTP](../results/integration/smoke_full.json)를 대조한다.

## 검색과 baseline

CLIP의 같은 pinned FP32 가중치와 전처리를 사용하고, 정규화 벡터를 FAISS HNSW IP로 검색한다.
관측 속성 relevance와 ANN/exact 일치율은 다른 지표다. 합성 키워드 환경의 BM25 우위도 보존한다.

| 모드 | MRR | NDCG@10 | BM25 MRR |
|---|---:|---:|---:|
| text | 0.940000 | 0.940000 | 1.0 |
| image | 0.880000 | 0.880000 | 적용 불가 |
| hybrid | 0.975000 | 0.975000 | 1.0 |

## 추천과 baseline

Two Tower의 전체 후보 top300을 DeepFM으로 순위화한 뒤 다양성·신규·탐색·GRU 세션을 적용한다.
오프라인 fixed-origin 품질은 B5 메모리 adapter이며, 라이브 Redis 귀속은 별도 실제 HTTP로 확인했다.

| 파이프라인 | HitRate@50 | NDCG@50 | Coverage |
|---|---:|---:|---:|
| train_popularity | 0.075072 | 0.016229 | 0.001000 |
| two_tower | 0.573510 | 0.186115 | 0.591380 |
| deepfm | 0.717278 | 0.388956 | 0.426920 |
| full_pipeline | 0.700885 | 0.342175 | 0.415340 |

정책 제약 후 DeepFM보다 지표가 낮아질 수 있다. 유리한 비교만 선택하지 않는다.
후보 baseline, 상대 lift, cohort와 분모는 원본 JSON의 `recommendation`에 모두 보존한다.
CTR/CVR 분류 결과 원본:

```json
{
  "ctr": {
    "auc": 0.964766793453099,
    "auc_status": "MEASURED",
    "logloss": 0.15979980922572484,
    "samples": 225422,
    "positives": 56639,
    "denominator": "observed exposures"
  },
  "cvr": {
    "auc": null,
    "auc_status": "UNDEFINED_SINGLE_CLASS",
    "logloss": 1.1620825780078663e-05,
    "samples": 56261,
    "positives": 0,
    "denominator": "observed clicked exposures"
  }
}
```

CVR의 단일 class AUC 미정의는 필수 CTR AUC 통과와 별개다. LogLoss만으로 전환 예측력을 주장하지 않는다.

## Docker 재현과 성능 수정

빈 data/models에서 데이터·임베딩·인덱스·세 모델을 준비한 실제 시간은 2725.892초다. 이미지 빌드와 최종 API 로딩은 별도다.
CLIP 사전 학습 다운로드 캐시와 Docker 의존성 레이어만 재사용했다. 데이터는 두 번 독립 생성해 모든 파일·split hash가 같았다.
첫 YAML 정렬 결함 실행은 새 test 전에 중지하고 데이터·미완료 모델·볼륨·로그를 보존했다.
4.1.0은 생성 mapping 순서를 식별자에 포함하며 prepare YAML도 순서를 보존한다.
첫 검색 p95 220.594/225.821ms와 FP32 graph만 적용한 후 hybrid 203.340ms 실패를 모두 보존했다.
같은 FP32 vision graph와 추론 프로세스 시작 전 CPU 예산 초기화를 적용했다. 학습 환경/가중치는 바꾸지 않았다.
전체 valid 400개 top10은 모두 같았고 최대 정규화 벡터 차이는 0.0000021160였다.
query cache identity에는 최적화 구현·batch-one shape·실제 시작 환경을 포함한다. full 품질도 이 경로로 평가했다.
별도 full CT 기능 fixture의 첫 실행은 paired CTR 뒤 API 준비 중 4GiB OOM 종료됐다. 평가 완료 후 프로세스를 교체해 동일 한도에서 재검증하며 최초 실패는 attempts/ct_lifecycle_memory_initial에 보존한다.
API 4GiB/4CPU, Linux ARM64 CPU, Torch 2.6.0+cpu·FAISS 1.9.0·Python 3.11, shared serving threads 2다.
각 모드 warmup 10회·순차 100회이며 CT/A-B 동시 부하 없는 초기 v1.0의 측정이다.
다른 CPU/GPU·동시 학습 부하·브라우저 픽셀 일치는 측정하지 않았다.

## A/B와 CT

A/B는 5000명/arm·30일·top10의 실제 합성 모의실험이다. 사용자별 적응 상태를 분리한다.
원본 전체 JSON은 해시 검증되는 [무손실 archive](../results/integration/ab_full_archive.json)에서 복원할 수 있다.
정확한 사용자 군집 CI·독립 사용자 Z/카이제곱은 원본 verifier로 재계산했다. 양의 lift나 유의성을 성공 조건으로 만들지 않았다.
CT 실행 상태는 PARTIAL, 재학습 판단은 RETAINED, 실제 reload/rollback은 False다.
10,000건의 실제 HTTP view 관측을 수집하고 세 모델을 재학습해 같은 valid cohort에서 비교했다.
자연 재학습이 RETAINED이면 별도 full controlled INITIAL fault 주입 시나리오의 승격·재로딩·롤백은 [분리된 증거](../results/integration/ct_controlled_lifecycle_full.json)를 따른다. 이 시나리오는 운영 품질 개선을 뜻하지 않으며 원래 운영 v1.0과 학습 후보 가중치는 보존한다.
monitor 성숙도는 명시적으로 query clock을 1시간 전진시킨 기능 시나리오이며 실제 1시간 대기나 운영 CTR 개선이 아니다.
새 chronological snapshot의 최신 관측은 시간 분할에 따라 보류되며 모든 새 이벤트가 학습 split에 들어간다고 주장하지 않는다.
[CT 원본](../results/integration/ct_full.json)과 실제 라이프사이클 로그를 확인한다.

## 제출 준비 범위

필수 여섯 검사는 [실행 집계](../results/integration/checks.json)와 최종 checker에서 대조한다.
공개 저장소 URL과 B11 PR #13 병합은 읽기 전용 원격 snapshot으로 확인했다. 개인 GitHub handle과 실제 팀원 리뷰는 추측하지 않는다.
외부 과제 시스템에 URL을 입력하는 행위는 수행하지 않았다. 최종 GitHub 반영은 승인된 기능 PR의 병합으로 수행한다.
