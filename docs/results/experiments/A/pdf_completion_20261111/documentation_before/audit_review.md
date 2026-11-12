# 코드 감사 범위와 실행 근거

B11의 기존 AST·mypy 오류는 final_submission/ 원본과 Git 이력에 보존했다.
INTEGRATE에서는 공개 함수의 누락 annotation, Optional·Tensor·FAISS·Windows 조건부 import와
자료구조 타입을 보완했다. 실제 전체 src/dashboard/docker 116개 파일과 제출/실행 script 8개의
mypy가 통과했다. 최종 checker의 별도 로그와 AST inventory로 재확인한다.
Any는 외부 framework/loader와 동적 backend 경계 등에 남아 있으며 완전한 strict typing을 주장하지 않는다.

AST inventory는 공개 signature, seed 호출과 의심 설정 상수를 보여 주며 실행·완전한 정적 증명을 대신하지 않는다.
주요 설정은 config YAML, 초기 CPU 예산·실행 경로는 Docker 환경변수로 관리한다.

| 발견 값의 의미 | 판정 |
|---|---|
| 기존 controlled CT 400상품/24사용자/6000이벤트 | 작은 기능 fixture이며 full 집계에 사용하지 않음 |
| API 계약 검사 top10 | 공개 스키마·개수 검사 입력이며 offline top50과 구분 |
| full CT top50·10000건 | 기본 CT threshold와 실제 관측·request HitRate 계약의 기능 검증 |
| seed42 | Python 시작 전에 PYTHONHASHSEED를 지정하고 config seed로 실제 학습/실험 실행 |
| CPU budget2·query batch1·224px | valid 성능 진단에서 확인한 고정 CLIP query 실행 경로; 가중치·정답·K·기준은 유지 |

성능 실패를 숨기지 않는다. 첫 full image/hybrid 220.594/225.821ms, FP32 graph 적용 후
hybrid 203.340ms 미달을 보존했다. native library 시작 예산과 worker 예산을 구분하고,
학습 완료 후 새 추론 프로세스에서 초기화하도록 수정한 뒤 HTTP를 재측정했다.
query cache에도 실제 초기 환경·구현·shape를 기록하며 full 품질은 같은 경로를 사용한다.

로컬 HTTP 소켓이 제한된 초기 부분 테스트는 중단 로그로 보존하고 정상 권한의 재검사로 구분했다.
최신 Docker/FP32/프로세스 예산 회귀 18개는 통과했으며 전체 최종 pytest와 pip/mypy 판정은
INTEGRATE 제출 checker의 실제 결과를 따른다. 이 문서만으로 최종 PASS를 선언하지 않는다.

CT의 자연 full valid 비교는 CTR AUC 0.971602→0.971574로 RETAINED다.
별도 full 초기 fault 기능 시나리오는 초기 ranker만 상수화하며 운영 모델을 바꾸지 않는다.
첫 기능 검증은 paired CTR 뒤 API 준비 중 4GiB 한도로 OOM 종료되어 원본을 보존했다.
평가와 HTTP 단계를 프로세스 교체로 분리한 재검사는 같은 4GiB 한도에서 종료 0으로 통과했다.
실제 HTTP 앱의 reload 로그와 registry의 승격·롤백 로그는 원본 두 경로를 각각 보존·검증한다.
자연 유지·약한 초기 fixture·실제 운영 개선은 최종 집계에서도 구분한다.
