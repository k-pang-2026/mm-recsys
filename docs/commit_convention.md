# 공통 커밋 메시지 규칙

사람이 메시지를 작성하지 않는다. Codex가 실제 diff를 요약하고 helper가 아래 형식으로
자동 생성한다. Git 작성자 설정은 유지하며 역할 이름을 다른 사람의 Git 신원으로 바꾸지 않는다.

```text
chore(shared): 공통 개발환경과 3인 병렬 개발 기반 구성

담당: 이제원 (A)
단계: SHARED

변경 사항:
- 추가: src/simulator/generate.py
- 수정: README.md

검증 결과:
- 종료 코드 0: .venv/bin/python -m pytest -q tests
구조 검증: 통과 / 규모: dev / 최종 품질: 미측정
데이터 식별자: 실제 검증한 fingerprint
```

위 본문은 형식 예제다. 실제 파일/명령/식별자를 대신하는 검증 근거로 쓰지 않는다.

제목은 `type(scope): 한국어 변경 요약`, 72자 이하, 한 줄이다. 변경 설명과 본문은
한국어로 작성하고 코드 경로·명령·기술 식별자는 원래 표기를 유지한다.

| type | 자동 선택 기준 |
|---|---|
| feat | 새 검색/추천/서빙 등 구현 파일 추가 |
| fix | 기존 구현 코드 수정 |
| test | 테스트만 변경 |
| docs | 문서만 변경 |
| chore | 공통 초기 환경·설정·의존성·자동화 변경 |

scope는 단계에 따라 shared/search/recommendation/platform/ct/docker/integration을 사용한다.
역할 계약 변경 WORKFLOW는 shared, A의 B10은 docker, C의 B9는 ct를 사용한다.
Docker 브랜치 PR의 제목을 검색 구현으로 만들지 않으며 C의 B11 제출 PR은 플랫폼 문서 제목을 사용한다.
검토된 main을 담당 브랜치에 가져올 때는 `chore(sync): 검토된 main 변경을 기능 브랜치에 반영`을
자동 사용한다. PR 병합은 한국어 Conventional Commit 형식의 PR 제목을 merge commit 제목으로
사용하며 본문에는 검증·리뷰 확인과 승인한 commit을 한국어로 기록한다.
단계별 실제 diff의 한국어 요약은 Codex가 `scripts/record_gate.py --summary "한국어 요약"`에
전달한다. 별도 요약이 없으면 helper가 실제 변경 경로의 영역을 묶어 한국어 제목을 생성한다.
본문의 추가/수정/삭제 파일, 검사 명령/종료 코드, 규모, 구조/최종 품질, data fingerprint는
Git 상태와 실제 gate에서 자동 읽는다. 실행하지 않은 검사를 본문에 추가하지 않는다.

`step_git.py --mode commit`은 메시지를 생성하고 로컬 commit을 만든다. Codex는
제목·변경 내용·검증·제한·commit·대상 원격 브랜치·로컬 PR 미리보기를 설명한 뒤
사용자에게 푸시·PR 생성 허가를 받는다. 허가 후 `--mode publish --approved`는 그 동일 commit을
기능 브랜치에 푸시하고 PR을 생성/갱신한다. 사용자 대신 --approved를
자동 생성하지 않는다. 새 commit으로 바뀌면 새 설명과 허가가 필요하다.
PR 병합은 [PR 절차](pr_workflow.md)의 안전 조건을 통과하면 자동 수행한다.
충돌·CI 실패·품질 미달·필수 리뷰 미완료를 강제로 통과시키지 않는다.
