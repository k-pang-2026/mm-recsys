# 제출 상태와 실행 근거

현재 소스의 검증 기준은 [v4.4 보고서](report.md)와 [요구사항표](requirements.md)다.
과거 v4.1/v4.2/v4.3 결과와 이전 최종 집계는 보존한다. 파일명만 같다는 이유로 과거 PASS를 새 측정으로 사용하지 않는다.

| 항목 | 현재 실행 근거 | 판정 범위 |
|---|---|---|
| 빈 산출물 full 준비 | [fresh_reproduction_full.json](../results/experiments/A/final_validation_20261112/fresh_reproduction_full.json) | 실제 생성·CLIP/FAISS·세 모델 학습, 빈 데이터·모델 경로에서 전체 재실행; HF 캐시 재사용 |
| 독립 데이터 재현 | [data_reproduction_full.json](../results/experiments/A/final_validation_20261112/data_reproduction_full.json) | 모든 기록 파일 해시 일치 |
| valid 동결·전체 test | [quality_full_test.json](../results/experiments/A/final_validation_20261112/quality_full_test.json) | 11개 품질·지연 기준과 후보 수 300; test 튜닝 없음 |
| 단건 실제 HTTP/Redis 지연 | [smoke_full.json](../results/experiments/A/final_validation_20261112/smoke_full.json) | 한 배포·10 warmup·100 serial·동시 CT 없음 |
| API 의미·스키마 | [pdf_examples.json](../results/experiments/A/final_validation_20261112/pdf_examples.json) | 텍스트/이미지/하이브리드의 실제 상품 속성·422/413 |
| live Redis MAB·세션 | [mab_full.json](../results/experiments/A/final_validation_20261112/mab_full.json) | 노출 귀속·최대 보상·중복 방지·세션 응답 |
| 브라우저와 세션 | [browser.json](../results/experiments/A/final_validation_20261112/browser_basic/browser.json) | 실제 여섯 탭·사진·클릭; 별도 live MAB 검증에서 귀속 확인 |
| 한 명령 API/A-B/CT | [demo_examples_verified.json](../results/experiments/A/final_validation_20261112/demo_examples_verified.json) | 20명/군·2일로 전체 명령 연결 검증; full A/B는 별도 측정 |
| full A/B | [ab_acceptance_full.json](../results/experiments/A/final_validation_20261112/ab_acceptance_full.json) | 5000명/군·30일·top10; 원본 보존·통계 재검산; 양의 lift 보장 없음 |
| 실제 full CT | [ct_full.json](../results/experiments/A/final_validation_20261112/ct_full.json) | 기존 실제 로그 13,404건으로 1회 감시 실행·세 모델 학습·valid 판정·watermark; 자동 worker 기동 별도 확인 |
| CT 라이프사이클 | [ct_acceptance_full.json](../results/experiments/A/final_validation_20261112/ct_acceptance_full.json) | 자연 승격이면 실제 교체·롤백; 유지이면 별도 통제 기능 시연과 명확히 분리 |
| 타입·전체 회귀·의존성·AST | [submission/checks.json](../results/experiments/A/final_validation_20261112/submission/checks.json) | 최종 checker의 실제 종료 코드와 원본 XML/텍스트 |
| 저장소 접근·기여 PR | [repository.json](../results/experiments/A/final_validation_20261112/submission/repository.json) | 현재 공개 접근 및 기존 14개 기여 PR의 읽기 전용 확인 |
| 최종 로컬 통합 | [final_acceptance.json](../results/final_acceptance.json) | 현재 모든 근거·해시를 실제 checker가 대조한 집계 |

미완료 실행의 파일이 아직 없는 동안 해당 항목은 미측정이다. 완료 여부는 요구사항표와 각 실행 파일의 상태를 따른다.
합성 A/B와 통제 CT를 실제 사용자 개선으로 해석하지 않는다. CT의 최신 관측이 모두 train에 들어갔다고 주장하지 않는다.
전체 catalog/cohort·시간순 분할·목표를 유지하며 실제 데이터 범위는 [사용자 전달 강사 결정](dataset_scope.json)의 RESOLVED_OPTIONAL을 따른다.

현재 소스는 로컬 수정본이다. 원격 push·PR·외부 과제 시스템 URL 제출은 수행하지 않았다.
현재 공개 저장소 주소는 https://github.com/k-pang-2026/mm-recsys 이며 기존 역할 기여/PR 원본은 [contributions.json](contributions.json)에 유지한다.
새 commit을 게시하려면 변경·검사·제한을 설명한 뒤 사용자의 명시적인 push 승인을 받는다.
