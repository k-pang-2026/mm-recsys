# 실행 지시만으로 개발하는 순서

공통 준비(SHARED)가 chore/shared-foundation → main PR로 병합된 뒤 세 사람은 **독립된 클론**에서 개발한다.
코드를 직접 입력하거나 Git 명령을 매번 작성할 필요가 없다. 아래 문장을 Codex에 보낸다.

| 사람 | 최초 입력 | 이후 반복 입력 | 담당 |
|---|---|---|---|
| 이제원(A) | `A 개발환경 준비하고 다음 단계 실행` | `A 다음 단계 실행` | B2a→B2b 검색, 마지막 INTEGRATE |
| 박정욱(B) | `B 개발환경 준비하고 다음 단계 실행` | `B 다음 단계 실행` | B3a→B3b→B4→B5 추천 |
| 박채영(C) | `C 개발환경 준비하고 다음 단계 실행` | `C 다음 단계 실행` | B6→B7→B8→B9→B10→B11 |

각 입력은 환경 확인, branch 동기화, 해당 단계 구현, 테스트, 실패 수정, gate 기록,
담당 파일의 로컬 커밋·PR 미리보기와 변경 설명까지 포함한다. 설명을 확인한 뒤
`설명한 B B3a 커밋을 브랜치에 푸시하고 PR 생성을 승인한다`처럼 지시하면 Codex가
push/원격 hash 확인과 main 대상 PR 생성·갱신을 수행한다. 기능 완료 PR은 안전 조건을
통과하면 자동 병합한다. 병합을 위해 다시 허가를 요청하지 않는다.
**사용자의 명시 허가 전에는 원격 푸시하지 않는다.** 역할·단계는
`config/team_workflow.yaml`, 구현 요구사항은 `ai_step_prompts_optimized.md`에서 자동 조회한다.
한 역할의 모든 단계를 요청해도 각 push 전에는 작업 설명과 허가가 필요하다.
다른 사람의 완료가 필요한 단계에서는 그 의존성을 알린다. 동일 승인 commit의 push 실패
재시도에는 기존 허가가 유지되지만 새 commit을 만들면 새 설명/허가를 받는다.

## 최초 한 번 필요한 것

- 각자 GitHub 저장소 접근/인증과 Codex 로그인이 필요하다. 비밀값을 채팅이나 저장소에 넣지 않는다.
- Python 3.10~3.12, Git, Docker Desktop/Engine 및 Compose가 설치·실행되어야 한다.
  Codex가 상태를 진단하고 가능한 범위의 복구를 수행한다. OS 권한/로그인/WSL Desktop 설정은
  직접 입력이 필요한 경우에만 정확한 조치로 안내한다.
- 클론도 Codex에 `https://github.com/k-pang-2026/mm-recsys.git를 클론하고 B 개발환경 준비`라고
  요청할 수 있다. 아직 저장소가 없는 위치에서는 이 최초 문장을 사용한다.

팀원 환경 준비는 Codex가 다음 명령을 실행한다.

```bash
bash setup_env.sh . --role=B
```

기본 setup은 패키지 설치·pip check·테스트·dev 데이터/이미지 생성·train/valid 진단·
CLIP cache/양 모달 실제 추론·Docker 사전 점검까지 수행한다. 하나라도 실패하면 nonzero다.
개발 데이터/모델은 푸시하지 않고 동일 config/seed로 재생성한다. 변경된 데이터는 조용히
재사용/덮어쓰지 않으며 새 버전 경로에서 재생성한다.

Docker를 실행할 수 없는 임시 머신에서 `--skip-docker-check`를 쓰면 해당 조건은
UNMEASURED다. 전체 환경 완료나 PDF Docker 통과를 의미하지 않는다.

WSL에서 Docker 명령을 찾을 수 없다는 메시지가 나오면 Codex는 Docker Desktop 실행 상태와
해당 배포판의 WSL Integration 설정을 함께 확인한다. 연동이 이미 켜져 있어도 Desktop이
종료되어 있으면 같은 오류가 발생한다. 설치된 Windows Docker CLI의 `docker.exe desktop start`로
시작하고 `docker info`, `docker compose config --quiet`, 실제 컨테이너 실행을 확인한 뒤
setup을 생략 옵션 없이 다시 실행한다. 전체 WSL 종료나 기존 컨테이너·볼륨 초기화는 하지 않는다.
[Docker의 WSL 연동 안내](https://docs.docker.com/desktop/features/wsl/)와
[Desktop 시작 CLI](https://docs.docker.com/desktop/features/desktop-cli/)를 따른다.

## VS Code Codex가 단계 지시를 처리하는 방식

1. `.venv`와 `.team/local.json`이 없으면 setup을 실행한다.
2. `scripts/team.py status`로 다음 단계를 조회한다.
3. `scripts/team.py prepare B`로 `feat/B/recommendation`을 생성/전환하고 필요한 원격
   main을 fetch/merge한다. 다른 역할의 의존성은 PR 병합된 main에서 확인한다.
   미병합·미완료 단계는 BLOCKED로 표시한다.
4. 가이드의 해당 단계를 구현하고 실제 검사 명령을 실행한다. 필요하면 최소 수정 후 다시 검사한다.
5. `scripts/record_gate.py`로 **실제 명령을 실행해** gate를 기록한다. gate JSON에 PASS만 수기로 쓰지 않는다.
6. `scripts/step_git.py --step <단계> --role B --mode commit`으로 담당 변경만 로컬 커밋한다.
   raw 데이터·모델·비밀·PDF는 제외한다.
   [공통 커밋 규칙](commit_convention.md)에 따라 한국어 변경 요약/본문을 자동 생성한다.
   사람은 커밋 메시지를 입력하지 않는다.
7. 변경·검사·미달 지표·commit·대상 origin/branch·PR 미리보기를 설명하고 푸시·PR 생성 허가를 요청한다.
8. 그 결과의 명시 허가를 받은 뒤에만 `scripts/team.py publish B --approved`를 실행해
   승인한 commit을 기능 브랜치에 push하고 원격 head와 PR head/base/draft를 확인한다.
   --approved를 자동으로 붙이지 않는다. 기능 완료 PR은 원격 gate·CI·품질·필수 리뷰와
   충돌 여부를 확인한 뒤 별도 허가 없이 자동 병합한다.

`prepare` 후 충돌이 나면 Codex가 파일 계약과 양쪽 작업을 읽어 해결하고 전체 회귀를 수행한다.
같은 파일을 여러 명이 편집하지 않도록 search/recommend/serving config overlay가 분리되어 있다.

## 선택: CLI 한 줄 실행

VS Code 대화 방식 대신 터미널에서 역할만 전달해도 된다.

```bash
bash scripts/codex_run.sh B
```

이 wrapper는 `codex exec --sandbox workspace-write`에 정해진 프롬프트를 전달한다.
모델에는 코드/검증/내용 설명을 맡기고 로컬 Git 커밋은 정상 사용자 권한의 runner가 수행한다.
Codex exit0만으로 진행하지 않고 실제 PASS gate를 확인한 뒤 **푸시 승인 대기에서 멈춘다**.
설명을 확인해 허가한 후 `B B3a 브랜치 푸시와 PR 생성 승인`이라고 Codex에 지시하거나 다음을 실행한다.

```bash
# 설명된 현재 로컬 commit의 push·PR 생성을 실제로 승인할 때만 실행
./.venv/bin/python scripts/team.py publish B --approved
```

승인 전 `codex_run.sh B`를 재실행해도 push하지 않는다. pending state와 승인 commit은
`.team/pending_publication.json`에 기록한다. 승인 후 push 실패는 동일 commit에 한해
같은 publish 명령 또는 wrapper 재실행으로 재시도한다. 새 commit은 다시 설명/허가를 받는다.
로그는 `.team/`에만 남긴다. runner는 사용자 로그인/인프라 권한을 대신하거나 sandbox를 우회하지 않는다.

최초 CLI 인증은 기존 Codex 인증을 재사용한다. 새 API 키 입력을 자동 요구하거나
프로젝트 API에 OpenAI 호출을 추가하지 않는다. 생성되는 검색·추천 시스템은 로컬 ML로 동작한다.

## 통합과 제출

C의 B7은 B5 추천 PR, B8은 B2b 검색 PR이 main에 병합된 뒤 진행한다. C의 B11 플랫폼 PR까지
병합되면 이제원이 `A 통합 단계 실행`을 지시한다. INTEGRATE는 main에서 `feat/integration`을
만들어 full 데이터/학습/성능/Compose 재현을 확인한다. 실패하면 valid에서 수정·재검증하고
숫자를 낮추거나 test 정답을 바꾸지 않는다. 최종 기준이 실제 PASS여야 로컬 통합 commit을
준비한다. 결과 설명과 허가 후 기능 브랜치를 push하고 최종 PR을 제출한다.

모든 변경은 PR로 main에 반영한다. 중간 단계는 Draft이고 기능 완료 시 검토 준비 상태로 전환한다.
기능이 완료된 PR은 푸시한 SHA의 gate·CI·품질·필수 리뷰/보호 규칙을 통과하고 충돌이 없으면
Codex가 자동 병합한다. 중간 Draft PR과 실패/미달 결과는 병합하지 않는다.
CI 대기가 10분을 넘으면 상태를 보존한다. `B 병합 상태 확인하고 계속 진행`으로 재개할 수 있다.
main 직접 push와 원격 보호 규칙 제거는 하지 않는다. [구체적인 PR 절차](pr_workflow.md)를 따른다.

공식 동작 근거: [AGENTS.md 자동 지침](https://learn.chatgpt.com/docs/agent-configuration/agents-md),
[Codex 비대화 실행](https://learn.chatgpt.com/docs/non-interactive-mode).
이 저장소의 단계 선택/검증/푸시 자동화는 별도로 구현한 프로젝트 기능이다.
