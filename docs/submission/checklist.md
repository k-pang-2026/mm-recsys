# 제출 상태와 인계

제출 URL은 https://github.com/k-pang-2026/mm-recsys 이다.
GitHub 외부 과제 시스템에 URL을 입력하는 행위는 아직 수행하지 않았다.
실제 원격 접근·PR head SHA·병합 여부는
[read-only 확인](../results/final_submission/repository.json)에 보존한다.
익명 접근 HTTP 200과 public 상태를 확인했으며 공개 범위를 바꾸거나 평가자를 초대하지 않았다.
개인 GitHub handle은 설정에 없으므로 미등록으로 유지한다.

PR #4의 API head aa619fb는 로컬에 없고 원격 pull ref도 제공되지 않았다.
실제 main의 #4 merge 69f66b2와 두 번째 부모 161eee5를 기여 근거로 대조했다.
두 head SHA를 같다고 주장하지 않으며 [불일치 기록](../results/final_submission/pr4_discrepancy.json)과
contributions.json의 설명에 함께 남겼다.

| 항목 | B11 상태 | 근거/남은 조치 |
|---|---|---|
| README·아키텍처·실행·기여 표 | 구현·검사 대상 | README 및 requirements 대응표 |
| B9/B10 원격 병합 | 확인 | PR #11 / #12, main e3af858 |
| full 품질/지연 | B10 실측 통과, 재집계 | final_acceptance.json의 12개 metric source/sha256 |
| clean clone 코드와 설정 | 별도 검사 | clone.json; Docker 전체 재생성과 구별 |
| 새 클론 full 데이터→학습→Compose | 미측정 | INTEGRATE 재현 필요 |
| 라이브 MAB 노출/보상 | UNCONNECTED | Redis와 B5 계약 연결, 실제 feedback 귀속 검증 |
| A/B | dev 실측, full 미측정 | 음의 lift 포함 ab_test_report.md |
| CT | controlled fixture 통과 | full 재학습·승격/유지·롤백 증거 필요 |
| 전역 타입 검사 | 실제 로그 공개 | mypy_repository.txt; 타입 누락은 python_audit.json |
| P0 외부 실제 데이터 요구 | UNRESOLVED | 강사 결정 부재, data_sources.md |
| B11 원격 push/PR | 명시 승인 대기 | 로컬 commit/PR 미리보기 설명 후 허가 필요 |
| INTEGRATE | 후속 단계 | B11 PR 병합 후 feat/integration |
| 과제 시스템에 URL 제출 | 미수행 | 제출 담당자가 최종 준비 상태를 확인한 뒤 수행 |

`scripts/check_submission.py --require-ready`는 미완료가 있으면 nonzero다.
`final_acceptance.json`의 UNMEASURED는 구조 게이트 PASS와 별개이며,
C의 엄격한 acceptance validator가 요구하는 최종 full PASS로 주장하지 않는다.
최종 통합에서 test 정답·K·분모·기준을 바꾸어 통과시키지 않는다.
모델/정책 수정이 필요하면 valid에서 선택·동결한 새 근거로 교체하고 이전 결과를 보존한다.

담당 역할 표는 [기여 원본](contributions.json), 실제 변경 내역은
[A](../contributions/A.md)·[B](../contributions/B.md)·[C](../contributions/C.md)를 따른다.
원격 snapshot에 없는 B11/INTEGRATE의 미래 작업을 완료된 기여로 집계하지 않는다.
