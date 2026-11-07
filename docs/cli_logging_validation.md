# 한국어 CLI·로그 검증 — 2026-11-07

이번 변경은 요청 10번의 출력 한국어화다. PDF의 출력 예시와 동료 평가 질문은 참고 자료로
확인했으며 예시의 점수·건수·전환율을 결과에 복사하지 않았다. 모델·평가 정답·기준·추천 정책은
변경하지 않았다. 기존 `.env`, `data/.gitkeep` 삭제, `docker/simulator.py`의 배치 상한 10,000 변경은 보존했다.
작업 브랜치는 `feat/cli-korean-logs`, 시작 SHA는 `09fdfd7`이다. 로컬 수정 상태이며 커밋·원격 푸시는 하지 않았다.

## 변경 연결

| 요청 | 구현 |
|---|---|
| 공통 시각·구성 요소·단계·상태, stderr 안내, UTF-8, 원본 traceback | `src/common/console.py` |
| Docker 시작·데이터·CLIP·FAISS·추천 모델 준비 | `docker/*entrypoint.py`, `docker/serve.py`, `docker/simulator.py`, `scripts/prepare_all.py`, `src/simulator/generate.py`, `src/search/build_{embeddings,index}.py` |
| 검색·추천·세션의 실제 HTTP 시연, 원본 JSON·파일 저장 | `scripts/demo.py` |
| 학습 epoch·손실·valid 지표 | `src/recommendation/train_{two_tower,deepfm,session}.py`, `scripts/train_all.py` |
| A/B 진행·실제 lift·p-value·95% CI | `src/evaluation/ab_test.py`, `ab_prepare.py` |
| CT 모니터링·누적 건수·재학습·승격·유지·롤백, 원본 JSONL 유지 | `src/ct/{storage,retrain_trigger,monitor,bootstrap,verify_ct}.py`, `docker/ct_worker.py` |
| Redis 경고·모델 교체 실패와 원본 예외 | `src/serving/{feature_store,ct_admin}.py` |
| 평가·검사 요약과 원본 JSON | `src/evaluation/run_all.py`, 평가·추천 검증 CLI, `docker/quality.py`, `scripts/check_submission.py`, `scripts/smoke_test.py` |
| Windows와 컨테이너 UTF-8 | Dockerfile 3개, `scripts/verify_console_utf8.ps1`, `tests/test_console.py` |

API JSON 키, 기존 CLI 옵션, 파일명, 모델 ID, 지표명은 유지했다. 평가 `run_all`은 품질 FAIL일 때
종료 코드 1을 반환한다. 진행 메시지를 파싱하던 외부 호출자는 이제 stderr를 읽어야 한다.
`--watch`는 스트리밍 JSONL이며, 1회 실행은 JSON 객체 하나다. 실패 시 stdout이 비어 있을 수 있고
원인·다음 조치·traceback은 stderr에 남는다.

## 현재 실행 결과

근거 디렉터리: [실행 산출물](results/experiments/A/cli_korean_20261107/).
모든 시각은 로그에서 UTC 오프셋으로 표시한다. `verification.json`에 코드·산출물 해시를 기록했다.

| 검사 | 실제 결과 | 근거 |
|---|---|---|
| 전체 회귀, 실제 Redis 포함 | **391 passed**, 2건의 라이브러리 deprecation 경고 보존 | `pytest_release.xml`, `pytest_release.log` |
| 정적 타입 검사 | **123 source files 통과** | `mypy_release.log` |
| Docker API·dashboard·simulator 이미지 빌드 | **통과**, 실제 빌드 | `docker_build_final.log` |
| full 준비 | 기존 호환 데이터·모델 재사용. 상품 50,000개·사용자 10,000명·이벤트 1,000,000건 | `compose_runtime.log`, preparation 원본 |
| 실제 API 검색 | text/image/hybrid 각각 10개 반환, 원본 JSON 파싱 통과 | `search_text.json`, `search_image.json`, `search_hybrid.json` 및 각각의 `.log` |
| 추천·세션 | 추천 10개, 시연 클릭 `applied=true`, recent_clicks에 P000001 반영, 관심=tote bag | `recommend.json`, `session.json` 및 `.log` |
| 컨테이너 안의 실제 검색 CLI | text 검색 성공, JSON stdout·한국어 stderr 분리 | `container_search.json`, `container_search.log` |
| Windows PowerShell 5.1 + 최종 컨테이너 | stdout/stderr=utf-8, 한글 문자열과 파일 재읽기 일치 | `powershell_final_stdout.json`, `powershell_final_stderr.log`, `powershell_final/` |
| 소규모 실제 A/B | 그룹별 8명, 1일, seed 42. CTR 변화 **−6.25%**, p=**0.8807434768**. CVR은 구매 없음으로 추론 불가 | `ab_small_final.json`, `ab_final_stdout.json`, `ab_final.log` |
| 운영 CT 모니터링 | v1.0, 신규 이벤트 720,086건, 임계치 10,000건. 성숙 요청 0 → 지표 **UNMEASURED**. 재학습 비활성 | `ct_monitor_final.json`, `ct_monitor_final.log` |
| 격리 CT 실제 학습·생명주기 | **PASS**. 알림·실제 재학습·승격·유지·롤백·API 교체 확인 | `ct_fixture.json`, `ct_fixture_stdout.json`, `ct_fixture.log`, `ct_log.jsonl` |
| 기존 제출 근거 검사 | **FAIL**, `evidence changed or missing: .env`. 한국어 원인·조치와 traceback 보존 | `peer_existing.log` |

A/B는 저장된 응답을 재생하지 않고 full 데이터의 기존 실제 추천 모델로 계산했다.
규모를 줄인 **출력 검증 실험**이며 PDF의 5,000명/그룹 최종 A/B 승인을 뜻하지 않는다.
CT는 기존 `verify_ct`의 **통제 fixture**다. 초기 ranker를 의도적으로 약하게 둔 별도 데이터에서
승격 경로를 검사하고 동일 후보의 유지·이전 버전 롤백을 검사한다. 운영 개선 수치로 해석하지 않는다.
운영 registry의 활성 모델은 v1.0을 유지했다. 로그 확인을 위해 운영 재학습을 시작하지 않았다.

처음의 전체 회귀는 19개 실패했다(`pytest.xml`, `pytest.log`). CT 테스트 fixture에 새 로그 필드를 추가했고 Redis 경고는 기존 `logging` 경로로 복구한 뒤
한국어 기대값을 검사했다. 나머지 17개는 모델 부재를 전제로 하는 API 테스트가 로컬 번들을
읽은 환경 간섭이었다. 저장소 공식 `src.serving.pytest_support` 플러그인을 적용하고,
명시적 설정을 전달하는 Redis 장애 테스트도 임시 모델 경로로 격리했다. 실제 모델 경로 검증은
위 Docker/API 실행에서 따로 수행했다. 원래 실패 로그도 보존했다.

## 재현 명령

사용자 CLI 예시는 [README](../README.md#한국어-cli실행-로그)에 있다. 실행했던 회귀 명령은 다음과 같다.

```bash
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONHASHSEED=42 \
REDIS_HOST=127.0.0.1 RUN_REDIS_TESTS=1 \
.venv/bin/python -m pytest -q -p src.serving.pytest_support tests

.venv/bin/python -m mypy --ignore-missing-imports src dashboard docker \
  scripts/demo.py scripts/prepare_all.py scripts/train_all.py scripts/smoke_test.py scripts/check_submission.py

docker compose build api-server dashboard simulator
docker compose up -d --no-build --pull never redis api-server dashboard

# 격리 fixture만 검사. work-dir은 실행마다 새로운 경로를 사용한다.
OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONHASHSEED=42 SCALE=dev \
.venv/bin/python -m src.ct.verify_ct --work-dir /tmp/새로운-ct-검사-경로 \
  --output docs/results/새로운-ct-검사.json
```

Windows 검사 스크립트는 UTF-8 BOM으로 저장하여 PowerShell 5.1이 소스의 한글도 정확히 읽는다.
Windows 실행 정책 때문에 첫 실행이 거부되어, 검토한 스크립트의 해당 프로세스에만 실행을
허용했다. UNC 경로에서 `.NET` 파일 저장 시에는 PowerShell provider 접두사가 없는
`ProviderPath`를 사용하도록 실제 실행 오류를 수정했다. 시스템 실행 정책은 변경하지 않았다.

## 이번 작업의 한계

- full 품질·최종 acceptance와 warm-up 10회/100회 정식 지연 벤치마크는 재측정하지 않았다.
- 최초 API 시연 지연은 text 1431.9ms, image 437.8ms, hybrid 220.3ms였다. 최초 로딩·다른 검사
  부하가 있는 단건 값이며 p95가 아니다. 실패 값을 숨기거나 200ms 통과라고 보고하지 않았다.
- 기존 제출 검사에서 `.env` 해시 불일치가 확인되었다. 기존 사용자 변경을 되돌리거나 과거
  근거를 갱신해 통과시키지 않았다. 변경된 소스에도 과거 full 품질 PASS를 재사용하지 않는다.
- 시뮬레이터 이미지 빌드·배치 회귀는 확인했으며 지속 실행/장시간 부하 검사는 하지 않았다.
- 실제 API·대시보드의 준비와 CLI를 확인했으며, 이번 작업에서 브라우저 화면 검사는 하지 않았다.
- 데이터·임베딩·모델은 커밋 대상에 넣지 않았다. 기존 단계 gate를 덮어쓰지 않았다.
