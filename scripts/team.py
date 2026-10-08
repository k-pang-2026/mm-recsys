#!/usr/bin/env python3
"""Resolve, prepare and run the next development stage; Git publishing is outside the model sandbox."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
import yaml

ROOT=Path(__file__).resolve().parents[1]


def workflow(root: Path = ROOT) -> dict:
    return yaml.safe_load((root/'config/team_workflow.yaml').read_text(encoding='utf-8'))


def gate(root: Path, step: str) -> dict | None:
    path=root/f'docs/results/gates/{step}.json'
    return json.loads(path.read_text()) if path.exists() else None


def completed(value: dict | None) -> bool:
    return bool(value and value.get('status')=='PASS' and value.get('acceptance')!='FAIL')


def select_stage(root: Path, role: str, plan: dict) -> str | None:
    for step in plan['order'][role]:
        value=gate(root,step)
        if not completed(value):return step
    return None


def dependencies(root: Path, step: str, plan: dict) -> list[str]:
    missing=[]
    for required in plan['stages'][step]['requires']:
        value=gate(root,required)
        if not completed(value):missing.append(required)
    return missing


def git(*args: str, root: Path = ROOT) -> str:
    result=subprocess.run(['git',*args],cwd=root,text=True,stdout=subprocess.PIPE,check=True)
    return result.stdout.strip()


def prompt(role: str, step: str) -> str:
    return f'''팀원 {role}로 {step} 단계만 끝까지 구현하라.
AGENTS.md, docs/codex_quickstart.md, config/team_workflow.yaml, docs/contracts.md,
ai_step_prompts_optimized.md의 A와 해당 단계 요구사항을 먼저 읽어라.
같은 역할의 장기 feature 브랜치에서 이전 산출물과 데이터 fingerprint를 확인하라.
수동 코드 작성 없이 네가 구현·의존성 검사·실제 검증·원인 수정·valid 튜닝을 수행하라.
완료되면 docs/results/gates/{step}.json과 docs/contributions/{role}.md를 실제 근거로 작성하라.
docs/commit_convention.md를 읽고 실제 diff의 한국어 요약을 record_gate.py --summary에 넣어라.
커밋의 type(scope), 한국어 변경 내역·검증 본문은 helper가 자동 생성한다.
파일 소유권 밖 변경이 필요하면 해당 역할 overlay/adapter로 해결하거나 통합 단계로 명시하라.
구조 검증 후 로컬 커밋을 준비하고 변경 내용·검사 결과·제한을 사용자에게 설명하라.
사용자가 그 결과의 푸시를 명시 승인하기 전에는 원격 푸시하지 마라.
모든 변경은 기능 브랜치에 push하고 main 대상 PR로 제출한다. main 직접 push는 금지한다.
push·PR 생성은 명시 허가 후 수행하고, 충돌·CI·품질·필수 리뷰 조건을 통과한 PR은 자동 병합한다.
병합을 위해 다시 허가를 요청하지 마라. 다른 역할 의존성은 PR 병합된 main에서 가져온다.
CLI runner에서 실행 중이면 .team/runner.json을 읽어라. publication_managed=true이면
Git 커밋·푸시는 외부 runner가 수행하므로 gate와 코드 검증만 완료하고 실제 push를 주장하지 마라.
미측정/full 미달을 숨기지 말고, model test 진단 전에 평가 기준을 고정하라.
실행할 수 없는 외부 인증/인프라 조건만 BLOCKED로 보고하라.
'''


def prepare(root: Path, role: str, step: str, plan: dict) -> None:
    if git('status','--porcelain',root=root):
        raise ValueError('local changes present; finish/publish prior work before automatic branch synchronization')
    git('fetch','origin',root=root)
    branch=plan['stages'][step].get('branch',plan['team'][role]['branch'])
    if branch==plan['base_branch']:raise ValueError('development must use a feature branch; main changes go through PR')
    # Check cross-role dependencies before creating/synchronizing any development branch.
    for required in plan['stages'][step]['requires']:
        own_branch=plan['stages'][required].get('branch',plan['team'][plan['stages'][required]['owner']]['branch'])
        if own_branch==branch:continue
        source=f"origin/{plan['base_branch']}"
        try:evidence=git('show',f'{source}:docs/results/gates/{required}.json',root=root)
        except subprocess.CalledProcessError:
            raise ValueError(f'{required} PR not merged into {source} yet') from None
        if not completed(json.loads(evidence)):
            raise ValueError(f'{required} has not passed in PR-merged {source}')
    branches=git('branch','--list',branch,root=root)
    if branches:git('switch',branch,root=root)
    else:
        remote=git('branch','--remotes','--list',f'origin/{branch}',root=root)
        if remote:git('switch','--track','-c',branch,f'origin/{branch}',root=root)
        else:git('switch','-c',branch,f"origin/{plan['base_branch']}",root=root)
    remote=git('branch','--remotes','--list',f'origin/{branch}',root=root)
    if remote:git('merge','--ff-only',f'origin/{branch}',root=root)
    # Integrate reviewed changes from main, not unpublished/unreviewed teammate branches.
    git('merge','--no-edit','-m',f"chore(sync): 검토된 {plan['base_branch']} 변경을 기능 브랜치에 반영",
        f"origin/{plan['base_branch']}",root=root)
    missing=dependencies(root,step,plan)
    if missing:raise ValueError(f'dependencies not verified yet: {missing}; resume when those teammates publish')


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['status','prompt','prepare','run','publish','merge'])
    parser.add_argument('role',nargs='?',choices=['A','B','C'])
    parser.add_argument('--step');parser.add_argument('--approved',action='store_true');args=parser.parse_args();plan=workflow()
    local=ROOT/'.team/local.json'
    role=args.role or (json.loads(local.read_text()).get('role') if local.exists() else None)
    if args.action=='status':
        print(json.dumps({r:{'name':plan['team'][r]['name'],'next':select_stage(ROOT,r,plan)} for r in plan['team']},ensure_ascii=False,indent=2));return 0
    if not role:raise ValueError('role required: scripts/team.py prompt|prepare|run A|B|C')
    pending=ROOT/'.team/pending_publication.json'
    if args.action=='publish':
        if not args.approved:raise ValueError('explain changes and obtain explicit user push approval first')
        if not pending.exists():raise ValueError('no local stage commit awaiting publication')
        publication=json.loads(pending.read_text())
        if publication['role']!=role:raise ValueError('another role has a pending publication in this clone')
        return subprocess.run([sys.executable,str(ROOT/'scripts/step_git.py'),'--step',publication['step'],
                               '--role',role,'--mode','publish','--approved'],cwd=ROOT).returncode
    if args.action in ('run','prepare') and pending.exists():
        publication=json.loads(pending.read_text())
        if publication['role']!=role:raise ValueError('another role has a pending publication in this clone')
        if args.action=='run' and publication.get('status')=='PUSH_APPROVED':
            return subprocess.run([sys.executable,str(ROOT/'scripts/step_git.py'),'--step',publication['step'],
                                   '--role',role,'--mode','publish','--approved'],cwd=ROOT).returncode
        print(f"AWAITING USER PUSH APPROVAL: {publication['role']}/{publication['step']} {publication['commit']}")
        print('Explain and review this commit; obtain explicit approval before team.py publish ROLE --approved.')
        return 0
    merge_pending=ROOT/'.team/pr/merge_pending.json'
    if args.action=='merge' or (args.action=='run' and merge_pending.exists()):
        if not merge_pending.exists():raise ValueError('no pending PR to merge')
        publication=json.loads(merge_pending.read_text())
        if publication['role']!=role:raise ValueError('another role has a pending PR in this clone')
        if args.action=='run' and publication.get('status')=='BLOCKED':
            args.step=publication['step']
            print(f"Repair published {role}/{args.step} before retrying merge: {publication.get('reason')}",flush=True)
        else:
            return subprocess.run([sys.executable,str(ROOT/'scripts/pull_request.py'),'--step',publication['step'],
                                   '--role',role,'--merge',str(publication['number']),'--commit',publication['commit'],'--wait'],cwd=ROOT).returncode
    step=args.step or select_stage(ROOT,role,plan)
    if not step:print(f'{role}: all assigned stages complete');return 0
    if step not in plan['stages'] or plan['stages'][step]['owner']!=role:raise ValueError('stage/owner mismatch')
    if args.action=='prompt':print(prompt(role,step));return 0
    dirty=git('status','--porcelain',root=ROOT)
    if dirty and args.action=='run':
        expected=plan['stages'][step].get('branch',plan['team'][role]['branch'])
        if git('branch','--show-current',root=ROOT)!=expected:
            raise ValueError('unfinished changes belong to another branch; preserve them before switching')
        # A failed model run can leave useful code. Resume it without silently discarding edits.
        changed=subprocess.run(['git','ls-files','-m','-o','--exclude-standard','-z'],cwd=ROOT,check=True,capture_output=True).stdout.decode().split('\0')
        prefixes=plan['paths'][role]+[f'docs/results/gates/{step}.json']
        if step not in ('SHARED','INTEGRATE') and any(name and not any(name.startswith(prefix) for prefix in prefixes) for name in changed):
            raise ValueError('unfinished changes include files outside this role ownership')
        missing=dependencies(ROOT,step,plan)
        if missing:raise ValueError(f'dependencies not verified yet: {missing}')
        print(f'Resuming unfinished {role}/{step} on {expected}',flush=True)
    else:
        prepare(ROOT,role,step,plan)
    if args.action=='prepare':print(prompt(role,step));return 0
    session=ROOT/'.team';session.mkdir(exist_ok=True)
    (session/'runner.json').write_text(json.dumps({'role':role,'step':step,'publication_managed':True}))
    command=['codex','exec','--sandbox','workspace-write','--cd',str(ROOT),
             '--output-last-message',str(session/f'{step}-final.md'),'-']
    try:
        result=subprocess.run(command,input=prompt(role,step),text=True,cwd=ROOT)
    finally:
        (session/'runner.json').unlink(missing_ok=True)
    if result.returncode:return result.returncode
    value=gate(ROOT,step)
    if not value or value.get('status')!='PASS':raise ValueError('Codex returned without verified PASS gate; no automatic publish')
    # INTEGRATE is publishable only after strict final acceptance is actually PASS.
    if step=='INTEGRATE' and value.get('acceptance')!='PASS':raise ValueError('final integration requires measured full acceptance PASS')
    return subprocess.run([sys.executable,str(ROOT/'scripts/step_git.py'),'--step',step,
                           '--role',role,'--mode','commit'],cwd=ROOT).returncode


if __name__=='__main__':
    try:raise SystemExit(main())
    except (OSError,ValueError,subprocess.CalledProcessError) as error:raise SystemExit(f'BLOCKED: {error}')
