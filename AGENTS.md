# Codex로 개발하는 3인 프로젝트

사용자는 공통 개발 기반을 먼저 완성해 GitHub에 푸시하고, 세 팀원이 각자 클론에서
짧은 단계 실행 지시만으로 구현·검증·수정·커밋을 수행하고, 작업 설명을 받은 뒤
사용자가 허가해야 기능 브랜치 푸시와 main 대상 PR 생성을 수행하도록 요청했다.
이 계약은 이 프로젝트의 정해진 역할/단계 실행에 적용한다. 사용자의 새 지시가 우선한다.

1. 시작할 때 `docs/codex_quickstart.md`, `config/team_workflow.yaml`,
   `docs/contracts.md`, `ai_step_prompts_optimized.md`의 A와 해당 단계를 읽는다.
2. `A 다음 단계 실행` / `B 다음 단계 실행` / `C 다음 단계 실행`은 해당 역할의 다음
   실행 가능한 단계를 구현·검증하고 해당 브랜치의 로컬 커밋까지 준비하는 요청이다.
   정상적인 수정/실험은 계속 수행하되, 원격 푸시 전 변경/검사/제한/commit을 설명하고
   사용자의 명시적인 푸시 허가를 받아야 한다. 단계 요청만으로 푸시를 승인한 것으로 간주하지 않는다.
3. 팀원은 독립 클론에서 작업한다. 같은 폴더에서 여러 역할을 동시에 실행하지 않는다.
   브랜치는 `feat/A/search`, `feat/B/recommendation`, `feat/C/platform`을 유지한다.
   SHARED는 `chore/shared-foundation` → main PR로 먼저 병합한 뒤 팀원들이 클론한다.
   A의 B10 Docker는 `feat/A/docker`에서 수행한다. C는 B9 플랫폼 PR을 먼저 병합하고,
   A는 B10 Docker PR 병합 후 `feat/A/submission`에서 B11 제출 문서 PR을 만든다.
   C의 담당 단계는 B9까지이며 A가 B10 → B11 → INTEGRATE를 순서대로 수행한다.
   INTEGRATE도 `feat/integration` → main PR로 제출한다. main 직접 커밋/푸시는 금지한다.
4. Python은 `.venv/bin/python` 또는 Windows `.venv/Scripts/python.exe`를 사용한다.
   환경이 없으면 `bash setup_env.sh . --role=<역할>`을 먼저 실행한다.
5. 구현 전 현재 Git 상태와 gate/산출물 fingerprint를 확인한다. 테스트 실패는 원인을 수정하고
   재검증한다. 품질 튜닝은 valid에서 수행하고 test 정답/기준을 변경해 통과시키지 않는다.
6. 구조 게이트를 통과하면 `scripts/step_git.py --mode commit`으로 변경 파일만 로컬 커밋한다.
   `docs/commit_convention.md`의 공통 규칙을 적용한다. 실제 diff의 한국어 요약을 record_gate
   --summary에 넣고 helper가 type(scope), 한국어 변경 내역과 실제 검증 본문을 자동 생성하게 한다.
   로컬 PR 미리보기와 변경 내용을 설명하고 푸시·PR 생성 허가를 받은 뒤에만
   `--mode publish --approved`를 실행한다. 원격 commit과 PR head/base/draft를 확인한다.
   `--approved`는 자동으로 붙이지 않는다. 사용자는 충돌 없고 안전한 PR의 자동 병합을
   허가했다. 원격 gate·CI·품질·필수 리뷰/보호 규칙과 푸시한 SHA를 확인해 자동 병합한다.
   병합 허가를 다시 요청하지 않는다. 절차는 `docs/pr_workflow.md`를 따른다.
   허가 후 push 실패 재시도는 동일 승인 commit에만 적용하며 새로운 commit은 다시 설명/허가를 받는다.
7. 외부 push 권한과 샌드박스 정책은 문서로 우회할 수 없다. 승인된 작업에는 정상적인
   escalation/auto-review를 사용한다. 강제 push·전체 권한 우회·비밀값 출력은 금지한다.
8. stage별 파일 소유권을 지킨다. 다른 팀원의 변경은 보존하고 의존성은 PR 병합된 main에서
   fetch/merge한다. 다른 역할의 미검토 기능 브랜치를 직접 합치지 않는다.
   단계별 paths가 있으면 역할 기본 소유권보다 우선한다. Docker/Compose/준비·smoke/컨테이너
   성능은 A B10 소유이며 README의 Docker 절차도 B10에서 작성한다. 제출 문서·제출 검사·
   final acceptance 집계는 A B11 소유이며 C의 평가·A/B·CT 결과를 사용한다.
   공통 역할 변경은 명시 요청한 WORKFLOW 단계에서 수행한다.
   충돌은 계약에 맞춰 해결·재검증하며 입력이 반드시 필요한 경우만 질문한다.
9. 데이터·이미지·임베딩·모델·캐시는 커밋하지 않는다. 클론에서 동일 config/seed로 재생성한다.
   결과와 gate는 실제 실행 근거만 기록하며 full 품질 미측정은 UNMEASURED로 남긴다.
10. 세 사람의 역할과 AI 하위 에이전트는 별개다. 요청되지 않은 하위 에이전트는 생성하지 않는다.
11. 한국어로 단계/검증/측정/commit/push/다음 명령을 보고한다. 가능한 작업을 완료한 뒤 응답한다.

## Ponytail: 작고 완전한 변경과 전체 프로젝트 감사

- 공식 `DietrichGebert/ponytail`의 고정 버전을 프로젝트 로컬에 보관한다. 출처·커밋·해시는
  [skills/ponytail-source.json](skills/ponytail-source.json), MIT 고지는 [skills/PONYTAIL_LICENSE](skills/PONYTAIL_LICENSE)에 있다.
- 코드 작성·수정·리팩터링에는 [Ponytail 기본 스킬](skills/ponytail/SKILL.md)을 읽고 `full`을 기본 적용한다.
  기존 구현 → 표준 라이브러리/플랫폼 → 설치된 의존성 순으로 재사용하고, 요구를 완전히 해결하는 최소 변경을 선택한다.
- 수정 전에 호출자·테스트·fixture·설정·실제 데이터 흐름을 확인한다. 간결화를 위해 입력 검증,
  데이터 손실 방지·오류 처리·보안·접근성·실제 하드웨어 검증·미션 요구를 삭제하지 않는다.
- `Ponytail-audit` / `ponytail-audit` / 전체 프로젝트 감사 요청에는
  [전체 감사 스킬](skills/ponytail-audit/SKILL.md)을 읽는다. 진입점·배포·의존성·테스트와 주요 흐름을 먼저 지도화한다.
- 감사 자체는 서비스 소스를 수정하지 않는 일회성 보고다. 요청된 스킬 설치·지침 반영은 수행하되,
  발견 사항의 기능 수정은 별도 수정 요청에서 진행한다. 재현 가능한 입력/상황이 없는 문제는 단정하지 않는다.
- 발견 사항은 필수 수정 / 권장 수정 / 선택 개선 순으로 최대 20개를 번호 매겨 보고한다.
  각 항목에 실제 파일·행, 동작, 재현 문제, 최소 수정안, 미수정 영향을 포함한다.
  실행한 검증과 과거 실행 근거, 미측정·미검토 범위를 구분한다.
- 이 프로젝트에서는 한국어로 보고하고 기존 역할·단계별 소유권, 평가 계약, 로컬 커밋 및 푸시 승인 규칙을 유지한다.
  하위 에이전트는 사용자 또는 적용 가능한 별도 지침의 명시 요청 없이 생성하지 않는다.
