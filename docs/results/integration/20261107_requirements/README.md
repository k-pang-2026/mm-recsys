# 2026-11-07 통합 보완 실행 근거

최종 판정은 `requirements.json`을 읽는다. 파일 존재만으로 통과한 것으로 보지 않는다.
실행 설명과 복사 가능한 명령은 `docs/requirements_completion.md`에 있다.

| 근거 | 내용 |
|---|---|
| `source_identity.json`, `artifact_manifest.json` | 기준 Git SHA, 소스 fingerprint와 커밋 대상 파일의 SHA-256 |
| `environment.json`, `windows_environment.json` | 실제 Windows·WSL·Docker 자원과 버전 |
| `data_audit_before.json`, `data_audit.json` | 수정 전 실패와 새 버전 EDA·페르소나 관측 |
| `preparation_initial.json`, `preparation_reuse.json` | 최초 full 준비와 호환 산출물 재사용 |
| `quality_full_valid.json`, `quality_selection_full.json`, `freezes/` | valid 선택과 불변 동결 근거 |
| `quality_full_test.json`, `smoke_full.json` | 실제 test 품질과 별도 단건 HTTP 지연 측정 |
| `demo_*.json`, `peer_review.json` | 실제 HTTP 검색·추천·세션 및 동료 평가 검사 |
| `ab_demo.json`, `ab_demo_verification.json` | 실제 전략 A/B, 사용자 단위 통계·분모·음의 lift |
| `ct_valid_memory_drill/` | valid 라벨 메모리 수정 후 격리 CT 전체 흐름 검증 |
| `ct_natural_oom_failure/` | 최초 full CT의 OOM 실패 원문과 메모리 진단 |
| `ct_first_recovered_run/`, `ct_second_recovered_run/` | 각 실패 뒤 완료된 학습 모델 검증과 중단된 paired valid 복구 |
| `ct_postfix_host_oom_failure/` | 컨테이너 한도 아래에서 발생한 호스트 전체 메모리 부족 실패 |
| `ct_natural.json`, `ct_execution.json`, `ct_postfix_memory.json` | 수정 후 신규 실제 로그로 정상 full CT 재실행 |
| `ct_*_training_full.json` | 최종 CT에서 실제 실행한 세 학습기의 보고서 |
| `browser.json`, `browser_*.png` | 실제 Chromium의 6개 탭·이미지·구매 원장·CLIP·클릭 비교 |
| `powershell/`, `powershell_search.json`, `compose_json_mode.json` | Windows·컨테이너 UTF-8 및 JSON stdout 검증 |
| `pytest_*.xml`, `mypy_final.log` | 회귀 검사 원본; testcase ID로 중복을 제거해 집계 |
| `execution.json`, `final_runtime.json` | 실행 명령·시각·종료 코드와 최종 서비스 상태 |

`*_stdout.json`은 실행 명령의 stdout 원문이다. 프로젝트 JSON CLI 결과는 단일 JSON이지만,
Docker 빌드·Compose 상태·PowerShell 진단처럼 다른 프로그램의 원문을 담은 파일은
텍스트 또는 JSONL일 수 있다. 이 파일을 현재 API 응답이나 유효한 단일 JSON으로 오인하지 않는다.
대응하는 `.log`는 stderr 원문이며 라이브러리 경고와 traceback을 보존한다.

실패·보조 실행은 최종 성공과 섞어 세지 않는다. `pytest_container_hostname_failure.*`,
`pytest_child_status_socket_sandbox.*`, `ct_drill_full_scale_failure/`,
`ct_watch_wall_clock_probe.*`, `browser_without_korean_font/`,
`browser_dashboard_startup_failure/`, `ct_recovery_parent_fingerprint_failure/`,
`before_auxiliary_log_completion/`을 보존했다.
`analysis/purchases.parquet`, 원본 데이터·모델·캐시는 커밋하지 않으며 같은 config/seed로 재생성한다.

이 집계는 사용자가 요청한 로컬 통합 보완의 근거다. 과거 B11 acceptance와 원격 제출 상태를
변경하지 않으며, 이번 코드가 GitHub에 게시됐다는 의미도 아니다.
