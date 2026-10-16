# 코드 감사 범위와 인계

B11의 [AST 원본](../results/final_submission/python_audit.json)은 src·dashboard·docker와
새 제출 검사 코드의 공개 함수 타입, seed 호출과 의심 설정 상수를 기록한다.
완전한 정적 분석이나 실행 결과를 대신하지 않는다. 누락된 타입 annotation은
전역 mypy와 별도로 공개하고, B/C 구현을 B11에서 수정하지 않는다.

## 의심 설정 상수 검토

| 위치 | 발견 값의 의미 | 판단 |
|---|---|---|
| src/ct/verify_ct.py | 400상품·24사용자·6000이벤트, 작은 학습 epoch/batch, seed42 | controlled fixture 구성·보고용 상수; 실제 full 설정으로 집계하지 않음 |
| src/evaluation/api_benchmark.py | top_n=10 | 기본 API 계약 검사; offline top50과 구별 |
| src/recommendation/bench_ranking.py, bench_tcp.py | top_n=50 | offline 추천 평가 K50을 사용한 기존 benchmark; 설정 일원화 검토는 INTEGRATE에 인계 |
| scripts/check_submission.py | top_k/top_n=10 | 공개 기본 API 스키마·개수 확인용 고정 계약 입력; 모델/정답/평가 기준을 튜닝하지 않음 |

이 표는 발견 값을 숨기는 allowlist가 아니다. 원본 위치·값은 계속 JSON에 남는다.
모델·시뮬레이터의 주 설정은 config YAML을 따르며, 이 좁은 탐지가 모든 숨은 상수를
찾았다고 주장하지 않는다. seed 호출 목록도 실제 설정 전달·전체 난수 재현을 증명하지 않는다.
pytest child process에는 실행 전에 PYTHONHASHSEED를 적용한다.

## 타입 검사

새 제출 검사 두 파일은 `--explicit-package-bases --follow-imports=silent`로 검사한다.
전역 검사는 별도 mypy 명령/전체 로그를 남기며, 오류를 구조 PASS로 바꾸지 않는다.
[mypy_repository.txt](../results/final_submission/mypy_repository.txt)에 드러난 Windows 전용
msvcrt 속성의 플랫폼 타입·Optional 처리·추천 자료구조 타입 등의 문제는
INTEGRATE/해당 역할에서 수정하고 다시 검사해야 한다.
이는 테스트의 기능 통과와 별개이며 최종 준비 상태의 BLOCKED 사유다.
