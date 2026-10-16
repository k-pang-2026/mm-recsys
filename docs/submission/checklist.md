# 제출 상태와 인계

제출 URL은 https://github.com/k-pang-2026/mm-recsys 이다. 외부 과제 시스템에 URL을 입력하는
행위는 수행하지 않았다. 저장소 public 상태·익명 HTTP 200·기여 PR #1–13은
[읽기 전용 원격 snapshot](../results/integration/submission/repository.json)으로 확인했다.
공개 범위 변경·평가자 초대는 수행하지 않았고 개인 GitHub handle은 미등록으로 유지한다.

PR #4의 API head aa619fb와 실제 보존 merge 69f66b2의 두 번째 부모 161eee5는 다르다.
[기존 불일치 기록](../results/final_submission/pr4_discrepancy.json)과 contributions.json의 설명을
보존하며 두 SHA를 같다고 주장하지 않는다.

| 항목 | 현재 확인한 상태 | 근거와 남은 조치 |
|---|---|---|
| B9/B10/B11 원격 병합 | 확인 | PR #11/#12/#13, main b40712a |
| full 데이터 독립 생성 | PASS | data_reproduction_full.json, 50K/10K/1M 두 번 hash 일치 |
| 빈 경로 full 데이터·임베딩·인덱스·모델 준비 | PASS | preparation_first_full.json, 2725.892초; HF 다운로드 cache 재사용 |
| 최종 Compose 네 서비스 | PASS | fresh_checkout.json, 빈 경로 준비 후 현재 추론 소스로 재배포·full HTTP/품질 검증 |
| live Redis MAB·세션 | PASS | mab_full.json, 귀속·중복·최대 보상·세션 응답 |
| full HTTP·후보·Redis 지연 | PASS | smoke_full.json 및 verified_full.json, 앞선 두 실패 보존 |
| 새 full valid/test 품질 | PASS | quality_full_valid/test.json, valid 동결 후 원래 기준 11개와 후보 수 통과 |
| full A/B | PASS | 5000명/arm·30일·top10, C 재검산, 음의 CTR/CVR lift 보존 |
| full CT | 기능 검증 PASS | 실제 10000건 수집·세 모델 학습·paired valid 자연 RETAINED, 별도 full 초기 fault 시나리오의 승격·실제 HTTP 재로딩/롤백 |
| 전역 타입 검사 | PASS | 116개 runtime 파일 및 8개 제출/실행 script 검사; 최종 checker 재실행 필요 |
| P0 실제 데이터 해석 | RESOLVED_OPTIONAL | dataset_scope.json, 강사 지시를 사용자가 전달함 |
| 최종 제출 회귀·준비 | 검사 원본 참조 | integration/submission/checks.json·pytest.xml, 실제 명령 종료 코드와 strict acceptance 대조 |
| INTEGRATE gate·로컬 commit | gate·Git 이력 참조 | 모든 mandatory check 실제 PASS 후 로컬 커밋하며 원격 승인은 별도 |
| INTEGRATE 원격 push/PR | 새 commit 승인 필요 | 구체적 변경·검증·제한·commit 설명 후 허가 |
| 외부 과제 시스템 URL 제출 | 미수행 | 저장소 준비·원격 반영과 별도 행위 |

현재 원본과 진행은 [INTEGRATE 보고서](../results/integration/report.md),
[진행 JSON](../results/integration/progress.json)을 따른다. 위 표는 완료되지 않은 작업을 PASS로 집계하지 않는다.
`check_submission.py --require-ready`는 미완료이면 nonzero다. 최종 strict acceptance는
원본 결과·전체 수치·full dataset·여섯 필수 check의 상태와 SHA를 모두 대조한다.
새 결과가 생성되기 전 B11의 과거 UNMEASURED를 최종 통합 PASS라고 주장하지 않는다.

데이터·이미지·임베딩·학습 가중치·캐시는 Git에 포함하지 않는다. A/B 집계의 큰 결과는
무손실 JSON archive로 원본 byte hash를 검증하며 raw 학습 데이터와 구별한다.
역할별 실제 기여는 [원본](contributions.json), [A](../contributions/A.md)·
[B](../contributions/B.md)·[C](../contributions/C.md)를 따른다.
