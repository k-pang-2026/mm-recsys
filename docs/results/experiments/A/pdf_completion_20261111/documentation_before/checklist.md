# 제출 상태와 인계

2026-10-20 생성기 4.2 통합의 실제 결과는
[현재 보고서](../results/integration/20261020_full/report.md)와
[최종 검사 원본](../results/integration/20261020_full/submission/checks.json)을 따른다.
제출 URL은 https://github.com/k-pang-2026/mm-recsys 이며 외부 과제 시스템에 URL을 입력하지 않았다.

| 항목 | 확인 범위 | 근거와 남은 조치 |
|---|---|---|
| 병합 main과 기여 PR | `aaa4184`, A/B/C 기여 및 PR18 실제 head | [읽기 전용 공개/PR snapshot](../results/integration/20261020_full/submission/repository.json) |
| 기존 full 품질 | 사용자 valid 동결·test 7파일을 바이트 그대로 보존·재사용; 50K/10K/1M과 현재 모델·소스 일치 | preserved_full_evaluation.json, verified_full.json |
| 빈 경로 full 준비 | 독립 원격 main 클론, 1906.485초; 데이터·검색·세 추천 모델 생성; HF 캐시와 소스 일치 이미지 재사용 | preparation_first_full.json, data_reproduction_full.json |
| Compose 네 서비스 | 새 준비 후 네 서비스 정상과 live API; 새 추천/인덱스/인코더 12파일 원본과 동일 | fresh_checkout.json, fresh_model_identity_full.json |
| 라이브 Redis MAB·세션 | 별도 Redis 관측으로 노출 귀속·최대 보상·중복 방지·세션 반응 검증 | mab_full.json |
| 새 full A/B | 군당 5000명·30일·top10, 실제 통계 재검산, CVR 상대 변화 −30.61% 보존 | ab_acceptance_full.json, ab_full_archive.json 및 11개 통계 shard |
| 자연 full CT | 실제 10000건 관측·세 모델 학습·checkpoint 재로딩·paired valid; 최소 개선 0.001 미달로 RETAINED | ct_full.json, ct_training_sources_full.json |
| 별도 full CT 기능 | 같은 실제 재학습 후보와 약한 초기 fixture, HTTP `v1.0→v1.1→v1.0` 교체·재로딩·롤백; 운영 개선과 구별 | ct_acceptance_full.json, ct_controlled_lifecycle_full.json |
| 실패와 복구 | 병렬 API OOM·4GB 단일 CT 비교 OOM·WSL 메모리 포화 보존; 저장 모델의 별도 비교로 복구 | parallel_load_failure.json, ct_memory_failure.json, docker_management_recovery.json |
| 영향받은 HTTP 부하와 단일 배포 지연 | 재학습/중복 API 없이 별도 재검사; benchmark 동안 replay 일시 정지 | separate_http_load_full.json, current_benchmark/smoke_full.json |
| 대시보드 | 실제 컨테이너 AppTest와 live 검색/추천 폼; 완료 전 UNMEASURED와 완료 후 최종 값 분리 | dashboard_full.json, 별도 dashboard_final.json; 브라우저 픽셀 미측정 |
| 전체 회귀·타입·의존성·AST 감사 | 실제 명령의 종료 코드·원본 로그·XML 참조 | submission/checks.json, pytest.txt·pytest.xml, mypy_*.txt, pip_check.txt, python_audit.json |
| P0 실제 데이터 해석 | RESOLVED_OPTIONAL; 개발 후 추가 검증용이며 미획득 | [사용자 전달 강사 결정](dataset_scope.json) |
| 종합 판정·gate·로컬 commit | full 품질과 여섯 필수 검사 상태·SHA가 실제 통과해야 PASS | final_acceptance.json, INTEGRATE gate 및 Git 이력 |
| 원격 push/PR | 새 commit의 변경·검사·제한 설명 후 명시 승인 필요 | 현재 단계 승인 대기; 안전한 병합은 기존 허가 범위 |
| 외부 과제 시스템 URL 제출 | 미수행 | 저장소 원격 반영과 별도 행위 |

각 파일명은 `docs/results/integration/20261020_full/` 기준이다. 최종 종합 판정은
`docs/results/final_acceptance.json`이다. `check_submission.py --require-ready`는 누락·불일치·미완료 시
nonzero이며 `publish_integration_dashboard.py`도 이를 대조한 뒤에만 대시보드 결과를 쓴다.

합성 A/B·view-only CT는 실제 사용자 개선을 입증하지 않는다. 자연 유지 결과와 별도
초기 fixture의 기능 검증을 분리한다. 기본 4GB CT의 한 프로세스 학습·비교 성공이나
다중 배포와 A/B·CT 병렬 실행 용량을 이번 분리 검증의 PASS로 주장하지 않는다.

PR #4의 API head aa619fb와 보존 merge 69f66b2의 두 번째 부모 161eee5 불일치는
[기존 기록](../results/final_submission/pr4_discrepancy.json)과 contributions.json에 보존했다.
공개 범위 변경·평가자 초대·개인 GitHub handle 추정은 수행하지 않았다.
데이터·이미지·임베딩·모델·캐시는 Git에서 제외하고, A/B 사용자 통계는 학습 데이터와 구별한
무손실 archive로 보존한다. 역할별 기여는 [원본](contributions.json), [A](../contributions/A.md)·
[B](../contributions/B.md)·[C](../contributions/C.md)를 따른다.
