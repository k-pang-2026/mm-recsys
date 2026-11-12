# 전체 코드 검토와 수정 근거

이 저장소는 합성 쇼핑 데이터를 생성하고 CLIP/FAISS 검색과 Two Tower → DeepFM → 재랭킹·GRU 추천을 제공한다.
Redis의 실시간 행동과 SQLite의 노출 귀속 로그를 이용해 모니터링·재학습·모델 교체를 수행한다.
검토 부하는 PDF의 full 50K 상품·10K 사용자·1M 이벤트, 한 Compose 배포, 단건 API와 순차 A/B·CT다.

[Ponytail 감사 지침](../../skills/ponytail-audit/SKILL.md)에 따라 README·배포·의존성·진입점·테스트를 지도화하고,
데이터 생성/시간분할 → 모델 학습 → API/Redis → 노출 귀속 → CT snapshot/승격/롤백 흐름을 검토했다.
사용자가 함께 요청한 리팩터링·오류 수정을 수행했다. 아래는 재현 가능한 문제와 반영한 최소 수정이다.

## 필수 수정 — 반영 완료

| 번호·위치 | 동작과 재현 문제 | 반영한 최소 수정 | 미수정 영향 |
|---|---|---|---|
| 1. [events.py:122](../../src/simulator/events.py#L122) | cart→purchase 설정을 바꿔도 전이 사전이 계산값으로 교체되어 설정 0/1이 지켜지지 않았다. | 설정 전이를 보존하고 중간 확률만 페르소나 CVR 비율로 보정했다. 0/1 경계·설정 검증을 추가하고 생성기 v4.4로 새 데이터를 생성했다. | 설정 재현과 PDF 페르소나/Markov 실험이 실제 생성 결과와 달라진다. |
| 2. [docker/simulator.py:125](../../docker/simulator.py#L125) | 기본 네 서비스는 로그만 쌓고 CT 감시 프로세스를 시작하지 않았다. | simulator가 CT worker를 감독하고 종료 시 자신의 자식 프로세스를 정리한다. 같은 루프백으로 검증 후 API 교체를 요청한다. | `docker compose up`만으로 자동 재학습이 작동하지 않는다. |
| 3. [monitor.py:35](../../src/ct/monitor.py#L35) | CTR/HitRate가 임계값과 정확히 같을 때 경고가 발생하지 않았다. | PDF의 ‘이하’에 맞게 `<=`를 적용하고 임계값 아래/같음/위·표본 부족을 검사했다. | 경계값의 성능 저하 알림이 누락된다. |
| 4. [ranking_labels.py:53](../../src/recommendation/ranking_labels.py#L53) | 노출 직후가 아닌 늦은 클릭에서는 구매 관측 기간이 덜 지났는데 CVR 음성으로 확정될 수 있었다. | 마지막 클릭+귀속 기간이 분할 종료 전에 끝났을 때만 미구매 음성을 사용한다. 실제 구매 양성은 유지한다. | 학습 정답에 미관측 음성이 들어간다. |
| 5. [storage.py:118](../../src/ct/storage.py#L118) | SQLite transaction context 종료만으로 연결은 닫히지 않는다. 반복 감시/쓰기에서 연결 종료가 호출되지 않았다. | `closing`과 transaction context를 함께 사용해 성공 시 commit, 실패 시 rollback 후 항상 close한다. | 연결과 파일 자원 수명이 불필요하게 길어진다. |
| 6. [serving/main.py:29](../../src/serving/main.py#L29) | 기본 Redis store 생성 뒤 모델 로딩이 실패하면 store 정리가 누락될 수 있었다. | lifespan 시작부터 finally로 감싸 서버가 소유한 store를 닫는다. 외부 주입 store의 소유권은 유지한다. | 시작 실패 뒤 연결이 남는다. |
| 7. [dashboard/explore.py:48](../../dashboard/explore.py#L48) | 화면 클릭 직전에 다른 추천을 새로 조회하고, 클릭 POST에는 원래 request ID를 전달하지 않았다. | 화면에 표시한 추천 응답/요청 ID를 보존해 클릭에 전달한다. 실제 Chromium 클릭과 SQLite join으로 확인했다. | 클릭이 실제 노출과 연결되지 않아 CT 라벨 근거가 빠진다. |
| 8. [Dockerfile.dashboard:11](../../docker/Dockerfile.dashboard#L11) | 한국어 표시 함수 추가 후 실제 경량 dashboard 이미지에 해당 모듈이 없어 `ModuleNotFoundError`로 화면이 실패했다. | 표준 라이브러리만 사용하는 text 모듈을 포함하고 이미지 빌드 중 `import dashboard.explore`를 검사한다. | 컨테이너 health는 정상이어도 화면을 실행할 수 없다. |
| 9. [scripts/demo.py:258](../../scripts/demo.py#L258), [verify_ct.py:154](../../src/ct/verify_ct.py#L154) | 자동/수동 CT가 기본 JSONL을 덮어쓰며, 별도 CT 시연도 같은 폴더의 이전 보조 학습 기록을 덮어쓸 수 있었다. | CLI는 고유 JSONL, 시연 보조 기록은 실행별 폴더로 분리한다. 두 번 실제 학습·승격·롤백한 뒤 두 원본 모두 재검증했다. | 이전 시연·자동 재학습의 실행 근거가 손상된다. |
| 10. [scripts/demo_host.py:72](../../scripts/demo_host.py#L72) | 임시 작업 컨테이너에서 `/tmp/...` 같은 출력 위치를 사용하면 `--rm` 종료와 함께 결과가 사라진다. | 호스트에 보존되는 저장소 `docs/results/` 아래 출력만 허용하고 절대 경로·OS 경로 구분자를 Linux 컨테이너 경로로 정규화한다. | 성공한 긴 실험의 결과 파일을 잃을 수 있다. |

## 권장 수정 — 반영 완료

| 번호·위치 | 동작과 재현 문제 | 반영한 최소 수정 | 미수정 영향 |
|---|---|---|---|
| 11. [search/transport.py](../../src/search/transport.py), [serving/main.py](../../src/serving/main.py) | 진입점에 따라 검색 JSON/multipart 처리 및 body 제한 경로가 달랐다. | 입력 처리를 한 middleware로 모으고 search API는 호환 진입점으로 유지했다. 422/413·양 진입점 검사를 통과했다. | 같은 API가 실행 명령에 따라 다른 입력 계약을 보일 수 있다. |
| 12. [metrics.py:52](../../src/evaluation/metrics.py#L52) | 여러 benchmark가 p50/p95/p99 계산을 각각 갖고 있었다. | 유한·비음수·비어 있지 않은 표본을 검증하는 공통 함수로 합쳤다. | 잘못된 표본과 백분위 계산의 수정이 일부 경로에만 반영될 수 있다. |
| 13. [reranking.py:65](../../src/recommendation/reranking.py#L65) 및 삭제 파일 | 호출하지 않는 common/data helper·entropy 함수, 전달만 하는 ColdStart wrapper, API와 중복된 simulator Dockerfile이 있었다. | 호출자·테스트·설정을 확인한 뒤 미사용 부분을 삭제하고 한 번 쓰는 정렬을 기존 재랭커에 합쳤다. 미사용 import도 정리했다. | 실행에 기여하지 않는 코드와 중복 이미지 정의를 계속 관리해야 한다. |
| 14. [제출 보고서](report.md), [요구사항표](requirements.md) | v4.1/v4.2 문서가 현재 완료 상태처럼 표시되어 새 실행 범위와 혼동되었다. | 현재 v4.4 실측과 진행 중인 검사를 구분하고 이전 원본을 보존했다. | 과거 PASS가 현재 소스의 합격 근거로 오인된다. |

## 실행 근거와 판정 범위

[현재 실측 보고서](report.md), [로컬 코드 검사](../results/experiments/A/pdf_completion_20261111/local_checks.json),
[실제 브라우저](../results/experiments/A/pdf_completion_20261111/browser_verified/browser.json),
[실제 클릭 귀속](../results/experiments/A/pdf_completion_20261111/browser_attribution.json),
[반복 CT 원본 보존](../results/experiments/A/pdf_completion_20261111/ct_repeat_verified.json),
[실패·복구 조건](../results/experiments/A/pdf_completion_20261111/execution_notes.json)을 대조한다.
위 감사 당시 full valid/test·단건 지연, 회귀 458개와 후속 호스트 16개 검사가 통과했다.
리팩터링 이후의 현재 품질·재현·A/B·CT 범위는 [현재 보고서](report.md)를 따른다.
최종 checker는 현재 전체 테스트를 다시 실행하며 [최종 실행 집계](../results/experiments/A/final_validation_20261112/submission/checks.json)에 종료 코드·원본을 남긴다.

판정: 위 필수·권장 수정은 반영했다. A/B·실제 full CT 및 최종 통합 상태는 실행 집계에서 확인한다.
간결화: 중복/미사용 파일 2개·단일 wrapper·미사용 함수/import와 중복 집계를 제거했다. 외부 의존성 추가는 0개다.
미검토/미측정: 외부 패키지 내부 전체 코드·최신 CVE 조사, GPU·다른 CPU·native Windows, 다중 배포/동시 학습 부하의 100회 p95, 실제 사용자 인과 효과.
모든 코드가 결함이 없다는 형식적 증명이나 strict typing 완성을 주장하지 않는다.
