# PDF 요구사항 재현 보고서 — 생성기 v4.4

현재 작업 소스에서 빈 v4.4 산출물 경로로 데이터를 생성하고 세 모델을 새로 학습했다.
full valid를 통과한 설정·소스·데이터·모델을 동결한 뒤 test를 실행했으며,
**품질·지연 11개 기준을 모두 통과했다.** K·정답·cohort·목표는 변경하지 않았다.
최종 통합 판정은 [submission/checks.json](../results/experiments/A/pdf_completion_20261111/submission/checks.json)과 [최종 집계](../results/final_acceptance.json)를 따른다.
이 문서의 품질 PASS는 실제 사용자 개선이나 원격 게시 완료를 뜻하지 않는다.

## 데이터와 재현

- seed 42, 상품 50,000개·사용자 10,000명·이벤트 1,000,000건·노출 2,254,172건, 시간순 80/10/10.
- 데이터 fingerprint: `2df9b64e07e3b2aad48c967c4c8d3d8b04883dd19279896bb374c4f9926ad7d8`.
- 데이터·검색 인덱스·추천 모델이 없는 새 경로에서 실제 준비 1,691.748초(약 28분 12초).
- 같은 Docker 환경에서 독립 생성한 데이터의 모든 기록 파일 해시가 일치했다.
- 기존 pinned CLIP 다운로드 캐시·Docker 의존성 레이어는 재사용했다. 과거 v4.3 산출물은 보존했다.
- 이번 검증은 수정 중인 로컬 소스와 빈 산출물의 재현이다. 새 원격 clone이나 미승인 소스 게시로 주장하지 않는다.

근거: [preparation_first_full.json](../results/experiments/A/pdf_completion_20261111/preparation_first_full.json), [data_reproduction_full.json](../results/experiments/A/pdf_completion_20261111/data_reproduction_full.json), [fresh_reproduction_full.json](../results/experiments/A/pdf_completion_20261111/fresh_reproduction_full.json).

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
| search_p95_ms | 85.921263 | 85.921263 | ≤200 | PASS |
| recommend_p95_ms | 34.196983 | 34.196983 | ≤200 | PASS |
| candidate_p95_ms | 3.394390 | 3.394390 | ≤100 | PASS |
| feature_p95_ms | 0.255806 | 0.255806 | ≤10 | PASS |

Recall@300은 전체 카탈로그의 사용자별 미래 cart/purchase 정답에 대한 macro 평균이다.
Coverage는 고정 전체 10,000명 Top-50 합집합/전체 50,000개이며, 후보 수는 300개다.
사용자가 확인한 계약대로 AUC ≥0.70은 CTR에 적용한다.
CVR AUC는 **0.530408**, 클릭 노출 54,375개 중 구매 양성 3,506개다.
CVR의 높은 예측력을 주장하지 않는다.

지연은 aarch64 CPU Docker 한 배포에서 CT·시뮬레이터를 멈추고 모드별 10회 준비+100회 순차 요청으로 측정했다.
API 4GiB/4CPU, 실제 추론 Torch/FAISS=2 threads, OMP/MKL/OpenBLAS=2, pinned FP32 CLIP을 사용했다.
Compose의 초기 환경값 1은 서버 시작 시 실제 추론 예산 2로 설정된다. 별도 품질 평가 프로세스는 Torch/FAISS=4 threads였다.
검색 p95는 text 23.791ms, image 81.350ms, hybrid 85.921ms이며 세 모드 중 최댓값을 판정했다.
동시 full 품질 평가 중 별도 단일 하이브리드 요청 402.1ms도 보존했다. 이 값은 위 단독 benchmark와 조건이 다르다.

원본: [quality_full_valid.json](../results/experiments/A/pdf_completion_20261111/quality_full_valid.json), [quality_selection_full.json](../results/experiments/A/pdf_completion_20261111/quality_selection_full.json), [quality_full_test.json](../results/experiments/A/pdf_completion_20261111/quality_full_test.json), [smoke_full.json](../results/experiments/A/pdf_completion_20261111/smoke_full.json).

## 결과 예시와 한 명령 시연

`docker compose up`으로 준비한 뒤 `demo examples`가 실제 검색 → 클릭 두 건 → 추천 → A/B → CT 시연을 실행한다.
새 Linux/WSL/macOS 클론에서는 `python3 scripts/demo_host.py --install`을 한 번 실행한다.
현재 작업 환경은 `demo`를 등록했다. Windows는 `python scripts/demo_host.py <명령>`을 사용한다.
기본 A/B는 5,000명/군·30일이며, 빠른 시연은 `--users-per-group 100 --days 7`이다.
이번 기본 규모의 전체 명령은 약 62.3분에 종료 코드 0으로 완료됐다.
대규모 실험 중 자동 CT의 `BUSY`를 실제 확인한 뒤 실험 완료까지 자동 학습을 잠시 멈췄다.
그 후 기본 자동 CT·100건/5초 수집을 복구한 상태에서 100명/군·7일의 동일 통합 명령도 완료했다: [demo_default_auto_verified.json](../results/experiments/A/pdf_completion_20261111/demo_default_auto_verified.json).
출력은 호스트에 보존되는 `docs/results/` 아래에 저장한다.
상품 ID·가격·점수·시간·통계는 실제 실행값이며 PDF p.10의 참고 숫자를 고정 출력하지 않는다.

실제 검색 의미·응답 검증: [pdf_examples.json](../results/experiments/A/pdf_completion_20261111/pdf_examples.json); 브라우저 여섯 탭·클릭: [browser_verified/browser.json](../results/experiments/A/pdf_completion_20261111/browser_verified/browser.json).
클릭의 실제 노출 귀속: [browser_attribution.json](../results/experiments/A/pdf_completion_20261111/browser_attribution.json); 전체 명령 기록: [demo_examples.txt](../results/experiments/A/pdf_completion_20261111/demo_examples.txt).

## A/B와 CT

각 군 5,000명·30일·top10의 합성 실험을 실행했다. CTR 상대 변화 -17.37%, p=0, 차이의 사용자 군집 95% CI=[-0.045131771347708245, -0.04171622865229168]. CVR 상대 변화 -27.72%, p=4.40971e-106, 차이의 사용자 군집 95% CI=[-0.0037009902322447286, -0.003092343101088603]. 음의 변화도 원본 그대로 보존하며 통계 검증 통과를 성능 개선으로 해석하지 않는다.

| 지표 | Control | Treatment | 상대 변화 |
|---|---:|---:|---:|
| CTR | 25.0049% | 20.6625% | -17.37% |
| CVR | 1.2253% | 0.8857% | -27.72% |

원본과 무손실 보관 근거: [ab_full_archive.json](../results/experiments/A/pdf_completion_20261111/ab_full_archive.json), [ab_acceptance_full.json](../results/experiments/A/pdf_completion_20261111/ab_acceptance_full.json).

오프라인 CTR AUC는 고정된 노출 표본에서 클릭·비클릭의 점수 순서를 평가한다. 이 A/B는 각 전략이 새로 노출한 Top-10 목록의 반응을 측정하므로, 높은 AUC가 더 높은 A/B CTR을 보장하지 않는다. 표의 CTR·CVR 분모는 노출 수이며, 위의 클릭 노출에 한정한 CVR AUC와도 평가 대상이 다르다. 이번 결과는 인기도 전략과 전체 추천 파이프라인의 비교다. 후보·랭킹·다양성 제약·MAB 각각의 기여를 분리한 실험은 하지 않았으므로 음의 효과의 단일 원인을 단정하지 않는다.

자동 full 재학습 판정은 **RETAINED**다. 누적 신규 로그 103,504건으로 트리거되었고, 동일 valid CTR AUC는 0.966056 → 0.965965다. 실제 학습·판정과 별도 통제 승격 시연을 구분한다. 운영 모델은 v1.0을 유지했다. 별도 full 통제 시연의 승격·롤백 성공을 운영 개선으로 해석하지 않는다.

근거: [ct_full.json](../results/experiments/A/pdf_completion_20261111/ct_full.json), [ct_training_sources_full.json](../results/experiments/A/pdf_completion_20261111/ct_training_sources_full.json), [ct_candidate_valid_full.json](../results/experiments/A/pdf_completion_20261111/ct_candidate_valid_full.json), [ct_acceptance_full.json](../results/experiments/A/pdf_completion_20261111/ct_acceptance_full.json).

| 새 관측의 시간순 위치 | 신규 이벤트 수 | 새 노출에서 관측된 CTR 라벨 수 |
|---|---:|---:|
| train | 0 | 0 |
| valid | 0 | 0 |
| test | 103,504 | 열지 않음 |

최신 로그가 test에 남아도 임의로 train으로 옮기지 않는다. 재학습은 새 시간순 스냅샷의 train을 사용하며, CT의 test 정답은 열지 않았다.

기본 네 서비스의 simulator가 자동 CT를 함께 시작한다. 신규 로그 10,000건이 트리거이며,
노출 라벨의 train/valid 양성·음성 조건이 부족하면 `WAITING_FOR_LABELS`로 대기한다.
Markov 피처 이벤트와 실제 API request ID에 연결한 합성 노출·클릭·구매를 구분해 저장한다.
원래 시간순 분할과 성숙 기간을 유지하므로 최신 관측이 test에만 남을 수 있다.
동일 valid CTR AUC의 최소 개선 0.001과 하한 0.70을 만족하는 후보만 실제 승격·API 교체한다.
A/B와 CT는 공유 잠금으로 순차 실행하며, `demo ct`의 기록은 실행별 파일로 분리한다.
`demo ct --drill`은 별도 400상품/24사용자 데이터와 약한 초기 모델에서 실제 학습·승격·HTTP 교체·롤백을 확인한다.
통제 시연의 성공을 운영 모델 개선이나 full 품질 개선으로 사용하지 않는다.

## 수정과 한계

설정된 cart 전이 확률이 무시되던 문제, CT 임계값의 등호 누락, CVR 음성 라벨의 성숙 시점,
SQLite 연결 종료, 기본 Compose의 CT worker 연결 누락을 수정했다.
대시보드 클릭에 원래 추천 요청 ID를 연결했고 실제 이미지의 누락 모듈도 수정·재빌드·브라우저 재검증했다.
검색 HTTP 입력 처리와 지연 집계의 중복을 합쳤고 미사용 데이터 helper·cold-start wrapper·중복 simulator Dockerfile·미사용 import를 제거했다.
원본 오류·실패·과거 실측은 [execution_notes.json](../results/experiments/A/pdf_completion_20261111/execution_notes.json)과 각 이전 결과 폴더에 보존한다.

H&M·Retailrocket·DeepFashion은 [사용자 전달 강사 결정](dataset_scope.json)에 따라 추가 검증용이며 이번 측정은 합성 데이터다.
다른 하드웨어/GPU, 다중 배포의 동시 학습 용량, 실제 사용자 인과적 개선, 원격 게시·외부 과제 제출은 이번 로컬 측정 범위가 아니다.
Docker가 보고한 총 RAM은 약 7.55GiB이며 API 할당은 4GiB/4CPU다. Windows 호스트의 물리 RAM 직접 조회는 WSL interop 오류로 미측정이다: [windows_host_hardware.json](../results/experiments/A/pdf_completion_20261111/windows_host_hardware.json).
역할별 기여와 실제 리뷰 기록은 [원본](contributions.json)을 유지한다. 새 소스의 push/PR은 수행하지 않았다.
