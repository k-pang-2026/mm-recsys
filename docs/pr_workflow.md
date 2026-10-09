# 기능 브랜치와 PR로 통합하기

main에는 검토한 PR을 병합한다. Codex는 기능 브랜치에서 구현·검증·한국어 자동 커밋과
로컬 PR 미리보기까지 준비하고 사용자에게 설명한다. **푸시와 PR 생성은 허가 후에만**
실행한다. 사용자는 **충돌 없고 문제가 없는 PR의 자동 병합**을 허가했다.
기능 완료 PR이 아래 안전 조건을 통과하면 병합을 위해 다시 확인하지 않는다.

| 작업 | 담당 | head → base | 검토 준비 시점 |
|---|---|---|---|
| 공통 준비 | 이제원(A) | chore/shared-foundation → main | SHARED 공통 구조 검사 통과 |
| 멀티모달 검색 | 이제원(A) | feat/A/search → main | B2b 완료 |
| 다단계 추천 | 박정욱(B) | feat/B/recommendation → main | B5 완료 |
| 서빙·평가·CT 플랫폼 | 박채영(C) | feat/C/platform → main | B9 완료 |
| Docker·컨테이너 성능 | 이제원(A) | feat/A/docker → main | B10 완료 |
| 제출 문서·검증 | 박채영(C) | feat/C/platform → main의 새 PR | B11 완료 |
| 공통 역할 계약 변경 | 이제원(A) | chore/team-workflow → main | 요청된 WORKFLOW 검사 통과 |
| 최종 통합 | 이제원(A) | feat/integration → main | INTEGRATE full acceptance PASS |

공통 PR을 먼저 병합한 뒤 B/C가 main을 클론하고 setup을 실행한다. 이후 세 명은 독립된
클론에서 검색·추천·Redis(B6)부터 병렬 개발한다. C의 B7은 추천 B5 PR 병합을,
B8은 검색 B2b PR 병합을 기다린다. C의 B9 플랫폼 PR을 먼저 병합하고, A는 B2b/B5/B9
병합 후 별도 feat/A/docker에서 B10 PR을 제출한다. C는 B10 병합 후 검토된 main을
feat/C/platform에 가져와 B11 새 PR을 제출한다. 필요한 다른 역할의 gate가 origin/main에 없으면
prepare가 중단한다. 각 브랜치는 검토된 main만 가져오며 아직 병합되지 않은 다른 기능
브랜치의 코드를 직접 가져오지 않는다.

검색·추천의 중간 단계와 C의 B6–B8은 한 PR을 Draft로 생성/갱신한다.
C는 B9에서 플랫폼 기능을 완료해 검토 준비 상태로 전환·병합한다. A의 B10은 별도 완료 PR,
C의 B11은 B9 PR 병합 후 같은 브랜치에서 만드는 새 제출 PR이다. 단계마다 새 PR을 만들지는 않는다. 미달 품질은 본문에 공개하고 Draft로
유지하며 실패를 고친 뒤 같은 단계에서 다시 검증한다. 최종 종합 품질 UNMEASURED와
구조 PASS는 별개다. SHARED PR은 모델 구현 전 공통 기반의 검토이며 PDF 전체 통과가 아니다.

## 사용자가 입력하는 문장

1. `B 다음 단계 실행`: Codex가 구현·검증·로컬 커밋과 PR 미리보기를 준비하고 설명한다.
2. `설명한 B B3a 커밋을 브랜치에 푸시하고 PR 생성을 승인한다`: 그 commit만 push하고
   main 대상 Draft PR을 생성/갱신한다. 원격 SHA와 PR의 head/base/draft를 확인해 URL을 보고한다.
3. 기능이 완료된 PR은 Codex가 푸시한 SHA의 원격 gate·CI·품질·필수 리뷰/보호 규칙과
   충돌 여부를 확인해 자동 병합한다. 별도 병합 허가 입력은 필요 없다.
4. CI가 아직 끝나지 않으면 최대 10분 기다린다. 이후에도 진행 중이면 상태를 보존한다.
   `B 병합 상태 확인하고 계속 진행`으로 같은 PR과 SHA의 안전 검사를 재개한다.

푸시와 PR 생성 허가가 명확하지 않으면 미리보기까지 준비해 범위를 확인한다. 브랜치 push만
성공하고 PR 생성이 실패하면 두 결과를 구분해 보고한다. pending 상태는 승인한 동일 SHA로
남아 있으므로 인증/권한을 복구한 뒤 기존 허가로 재시도한다. 새 commit은 다시 설명/허가를 받는다.

팀원은 PR의 실제 변경을 리뷰한다. 저장소가 필수 리뷰를 요구하면 해당 조건이 충족되어야 병합한다. 권장 순서는 A의 검색을 B가, B의 추천을 C가,
C의 플랫폼을 A가, A의 Docker를 B/C가 리뷰하는 것이다. 리뷰·기여 기록은 실제 PR/commit URL로 연결하며 실행하지
않은 리뷰를 만들지 않는다. 리뷰 댓글/승인을 Codex에 맡길 때도 실제 리뷰를 요청해야 한다.
저장소 보호 규칙의 필수 리뷰 조건은 GitHub가 추가로 적용한다. helper는 Draft·SHA 불일치,
원격 gate 실패·품질 미달·common CI 미통과·다른 진행/실패 검사·미해결 변경 요청·미완료 기능을
병합하지 않는다. GitHub의 mergeable=true와 mergeable_state=clean을 확인하고 병합 직전
head/base SHA와 PR 상태를 다시 읽는다. 검사 중 기준 main이나 head가 바뀌면 중단하고 동기화·
재검증한다. 충돌이나 보호 규칙을 강제로 우회하지 않는다.

## Codex가 호출하는 도구

로컬 커밋 시 `.team/pr/<STEP>.md`와 JSON을 자동 작성한다. 여기에는 한국어 PR 제목,
실제 변경 파일 수, 담당·단계·SHA, 실행 명령·종료 코드, 규모·품질·데이터 식별자가 들어간다.
미리보기는 로컬 작업이며 인증을 읽거나 원격 PR을 생성하지 않는다.

```bash
# 로컬 준비와 미리보기: 원격 변경 없음
./.venv/bin/python scripts/step_git.py --step B3a --role B --mode commit
# 설명한 commit의 push·PR 생성에 사용자가 명시 허가한 뒤에만
./.venv/bin/python scripts/team.py publish B --approved
# CI 대기/검증을 재개하고 안전할 때만 자동 병합
./.venv/bin/python scripts/team.py merge B
```

PR 발행은 승인 후 GitHub API로 기존 open PR을 찾고 없으면 생성하며 있으면 본문을 갱신한다.
GitHub CLI를 새로 설치할 필요가 없다. 기존 Git credential 또는 GH_TOKEN/GITHUB_TOKEN을
메모리에서 사용하고 값을 파일/로그/채팅에 남기지 않는다. Git push 인증과 PR API 권한은
다를 수 있으며 실제 API 권한 확인은 승인된 발행 시 수행한다. GitHub 계정은 아직 미등록이므로
리뷰어 계정·초대·보호 규칙을 추측하거나 자동 변경하지 않는다.

병합은 승인한 SHA를 조건으로 `merge` 방식을 사용해 기능의 한국어 커밋 이력을 보존한다.
최종 INTEGRATE도 별도 PR로 제출해 full acceptance와 모든 안전 조건을 통과하면 자동 병합한다.
자동 병합 대기/차단 사유는 `.team/pr/merge_pending.json`, 실제 결과는 merge_result.json에 기록한다.
GitHub 저장소의 auto-merge 기능을 켜거나 관리자 설정을 변경하지 않고 helper가 조건을 검사한다.
실제 원격 실행 증거가 생기기 전에는 PR/CI/병합 성공을 보고하지 않는다.

API 근거: [GitHub PR 생성·갱신·병합 API](https://docs.github.com/en/rest/pulls/pulls),
[GitHub API 인증](https://docs.github.com/en/rest/authentication/authenticating-to-the-rest-api).
