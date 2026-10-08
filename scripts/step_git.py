#!/usr/bin/env python3
"""Scoped, approved feature publication and PR creation; credentials are never printed."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

OWNERS={'SHARED':'A','INTEGRATE':'A','P0':'A','B0':'A','B1':'A','B2a':'A','B2b':'A',
        'B3a':'B','B3b':'B','B4':'B','B5':'B',**{f'B{i}':'C' for i in range(6,12)}}


def commit_message(step: str, role: str, files: list[str], value: dict, plan: dict | None) -> str:
    """Create a Conventional Commit with Korean change details from the verified diff."""
    scope=('shared' if step in ('SHARED','P0','B0','B1') else 'integration' if step=='INTEGRATE'
           else 'search' if step in ('B2a','B2b') else 'recommendation' if role=='B'
           else 'ct' if step=='B9' else 'docker' if step=='B10' else 'platform')
    content=[name for name in files if not name.startswith('docs/results/gates/')]
    if step=='SHARED':kind='chore'
    elif content and all(name.startswith('docs/') or name.endswith('.md') for name in content):kind='docs'
    elif content and all(name.startswith('tests/') or name in ('pytest.ini','mypy.ini') for name in content):kind='test'
    elif any(name.startswith(('src/','dashboard/')) for name in content):
        kind='feat' if any(not git('ls-files','--',name) for name in content if name.startswith(('src/','dashboard/'))) else 'fix'
    else:kind='chore'
    labels=[]
    for prefix,label in [('src/common/','공통 계약'),('src/simulator/','시뮬레이터'),('src/search/','검색'),
                         ('src/recommendation/','추천'),('src/serving/','서빙'),('src/evaluation/','평가'),
                         ('src/ct/','지속 학습'),('scripts/','개발 자동화'),('config','설정'),
                         ('tests/','테스트'),('docs/','문서'),('docker','컨테이너'),('requirements','의존성')]:
        if any(name.startswith(prefix) for name in content):labels.append(label)
    summary=value.get('commit_summary_ko') or ('·'.join(labels[:3])+' 변경 반영' if labels else '검증한 변경 사항 반영')
    if not isinstance(summary,str) or '\n' in summary or '\r' in summary or not re.search('[가-힣]',summary):
        raise ValueError('commit summary must be one Korean line describing actual changes')
    title=f'{kind}({scope}): {summary}'
    if len(title)>72:raise ValueError('commit title must be at most 72 characters; shorten the Korean summary')
    name=plan['team'][role]['name'] if plan else role
    changes=[f"- {'삭제' if not Path(path).exists() else '수정' if git('ls-files','--',path) else '추가'}: {path}" for path in files]
    checks=[f"- 종료 코드 {entry['exit_code']}: {entry['command']}" for entry in value['commands']]
    acceptance={'UNMEASURED':'미측정','FAIL':'미달','PASS':'통과'}[value['acceptance']]
    return '\n'.join([title,'',f'담당: {name} ({role})',f'단계: {step}','','변경 사항:',*changes,'',
                      '검증 결과:',*checks,f"구조 검증: 통과 / 규모: {value['scale']} / 최종 품질: {acceptance}",
                      f"데이터 식별자: {value['data_fingerprint']}",''])


def git(*args: str, capture: bool = True) -> str:
    result=subprocess.run(['git',*args],check=True,text=True,
                          stdout=subprocess.PIPE if capture else None)
    return (result.stdout or '').strip()


def check_gate(value: dict, step: str, role: str) -> None:
    if value.get('step')!=step or value.get('owner')!=role or value.get('status')!='PASS':
        raise ValueError('step/owner/status mismatch; verified structural PASS required')
    commands=value.get('commands')
    if not isinstance(commands,list) or not commands or any(
        not isinstance(c,dict) or not c.get('command') or c.get('exit_code')!=0 for c in commands):
        raise ValueError('successful command evidence required')
    if value.get('scale') not in ('dev','full') or value.get('acceptance') not in ('PASS','FAIL','UNMEASURED'):
        raise ValueError('scale and separate acceptance status required')
    if value['scale']!='full' and value['acceptance']=='PASS':raise ValueError('dev cannot establish full acceptance')
    if step=='INTEGRATE' and value['acceptance']!='PASS':raise ValueError('final integration requires full acceptance PASS')
    for key in ['data_fingerprint','config_fingerprint','evaluation_version']:
        if not isinstance(value.get(key),str) or not value[key].strip():raise ValueError(f'missing {key}')


def validate_path(root: Path, raw: str, allow_deleted: bool = False) -> str:
    path=Path(raw);target=root/path
    if path.is_absolute() or '..' in path.parts or raw.startswith('-'):
        raise ValueError(f'only relative repository files allowed: {raw}')
    deleted=allow_deleted and not target.exists() and subprocess.run(
        ['git','ls-files','--error-unmatch','--',raw],cwd=root,capture_output=True).returncode==0
    if not target.resolve().is_relative_to(root) or target.is_symlink() or (not target.is_file() and not deleted):
        raise ValueError(f'not a regular repository file: {raw}')
    if any(part in ('.git','.venv','.cache','.team','.aws','.codex','.agents','data','models') for part in path.parts):
        if path.as_posix() not in ('data/.gitkeep','models/.gitkeep'):raise ValueError(f'bulk/private file excluded: {raw}')
    if path.name.startswith('.env') and path.name not in ('.env','.env.example'):raise ValueError(f'private env excluded: {raw}')
    if path.suffix in ('.pem','.key','.pt','.faiss','.parquet','.pdf') or (not deleted and target.stat().st_size>2_000_000):
        raise ValueError(f'binary/private/large file excluded: {raw}')
    if path.name=='.env' and not deleted:
        for line in target.read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key,value=line.split('=',1)
                if re.search('TOKEN|SECRET|PASSWORD|API_KEY',key.upper()) and value.strip():
                    raise ValueError(f'non-public .env key cannot publish: {key.strip()}')
    return path.as_posix()


def discover_files(root: Path) -> list[str]:
    output=subprocess.run(['git','ls-files','-m','-o','--exclude-standard','-z'],check=True,capture_output=True).stdout
    files=[]
    for name in dict.fromkeys(output.decode().split('\0')):
        if not name:continue
        try:files.append(validate_path(root,name,allow_deleted=True))
        except ValueError:print(f'Excluded from automatic stage publication: {name}')
    return files


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--step',required=True,choices=OWNERS);parser.add_argument('--role',required=True,choices=['A','B','C'])
    parser.add_argument('--mode',choices=['check','commit','publish'],default='check');parser.add_argument('--files',nargs='+')
    parser.add_argument('--approved',action='store_true',help='publish only after the user reviewed this commit and explicitly approved its push')
    args=parser.parse_args()
    if args.mode=='publish' and not args.approved:
        raise ValueError('push requires explicit user approval after the change explanation; use --approved only after that approval')
    if OWNERS[args.step]!=args.role:raise ValueError(f'{args.step} owner is {OWNERS[args.step]}')
    root=Path(git('rev-parse','--show-toplevel')).resolve()
    if Path.cwd().resolve()!=root:raise ValueError('run from repository root')
    branch=git('branch','--show-current')
    allowed=[f'feat/{args.role}/{args.step}-']
    plan_path=root/'config/team_workflow.yaml';plan=None
    if plan_path.exists():
        import yaml
        plan=yaml.safe_load(plan_path.read_text())
        expected=plan['stages'][args.step].get('branch',plan['team'][args.role]['branch'])
        valid_branch=branch==expected
    else:valid_branch=bool(re.fullmatch(rf'feat/{args.role}/{re.escape(args.step)}-[A-Za-z0-9._-]+',branch))
    if branch in ('main','master') or (plan and branch==plan['base_branch']):
        raise ValueError('main direct commit/push forbidden; use a feature branch and PR')
    if not valid_branch:raise ValueError(f'use assigned feature branch for {args.role}/{args.step}')
    remote=git('remote','get-url','origin')
    if not (remote.startswith('https://github.com/') or remote.startswith('git@github.com:')):raise ValueError('reviewed GitHub origin required')
    if plan and remote.removesuffix('.git')!=plan['repository'].removesuffix('.git'):
        # SSH clone of the same GitHub repository is also accepted.
        ssh='git@github.com:'+plan['repository'].split('github.com/',1)[1]
        if remote.removesuffix('.git')!=ssh.removesuffix('.git'):raise ValueError('origin differs from configured team repository')
    if git('diff','--cached','--name-only'):raise ValueError('existing staged changes: finish that commit first')
    gate_path=f'docs/results/gates/{args.step}.json'
    value=json.loads((root/gate_path).read_text());check_gate(value,args.step,args.role)
    if args.step=='INTEGRATE':
        import sys
        sys.path.insert(0,str(root))
        from src.common.config import load_config
        from src.evaluation.acceptance import validate_acceptance
        cfg=load_config()
        report=json.loads((root/'docs/results/final_acceptance.json').read_text())
        manifest=json.loads((root/cfg['paths']['data_dir']/'split_manifest.json').read_text())
        validate_acceptance(report,cfg,manifest,root)
    files=[] if args.mode=='publish' else (list(dict.fromkeys(validate_path(root,f,allow_deleted=True) for f in args.files)) if args.files else discover_files(root))
    if files and gate_path not in files:raise ValueError(f'include gate evidence: {gate_path}')
    if plan and args.step not in ('SHARED','INTEGRATE'):
        for name in files:
            if name==gate_path:continue
            if not any(name.startswith(prefix) for prefix in plan['paths'][args.role]):
                raise ValueError(f'outside {args.role} ownership: {name}; use role overlay/adapter')
    if value.get('source_hashes'):
        import hashlib
        for name,digest in value['source_hashes'].items():
            if hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest:
                raise ValueError(f'changed after verification: {name}; rerun gate checks')
    git('diff','--check','--',*files)
    print(json.dumps({'branch':branch,'origin':remote,'files':files,'acceptance':value['acceptance']},ensure_ascii=False,indent=2))
    if args.mode=='check':print('CHECK ONLY');return 0
    pending=root/'.team/pending_publication.json'
    if args.mode=='publish':
        if not pending.exists():raise ValueError('no reviewed local stage commit; run commit mode and explain changes first')
        publication=json.loads(pending.read_text())
        if (publication.get('step'),publication.get('role'),publication.get('branch'),publication.get('commit'))!=(args.step,args.role,branch,git('rev-parse','HEAD')):
            raise ValueError('pending commit changed since review; explain and obtain new approval')
        commit=publication['commit']
        publication['status']='PUSH_APPROVED'
        pending.write_text(json.dumps(publication))
        pr_required=bool(plan and plan.get('pull_requests',{}).get('required'))
        if pr_required:
            from scripts.pull_request import GitHubAPI,render,ensure
            description=render(root,args.step,args.role,plan,value)
            client=GitHubAPI(root,plan)
            client.preflight()
        git('push','-u','origin',branch,capture=False)
        observed=git('ls-remote','origin',f'refs/heads/{branch}').split()
        if not observed or observed[0]!=commit:raise ValueError('remote head differs; verify concurrent publication before retry')
        if pr_required:
            result=ensure(root,description,client)
            print('PR VERIFIED:',result['url'],'draft:',result['draft'])
        pending.unlink(missing_ok=True)
        print('PUSH VERIFIED:',commit)
        if pr_required and not result['draft']:
            from scripts.pull_request import automatic_merge_enabled,auto_merge
            if automatic_merge_enabled(plan):
                auto_merge(root,client,plan,args.step,args.role,result['number'],commit,wait=True)
        return 0
    if pending.exists():
        publication=json.loads(pending.read_text())
        if publication.get('step')!=args.step or publication.get('role')!=args.role:
            raise ValueError('another stage is awaiting push approval; finish that reviewed commit first')
    if files:
        message=commit_message(args.step,args.role,files,value,plan)
        git('add','--',*files,capture=False)
        subprocess.run(['git','commit','--file','-'],input=message,text=True,check=True)
    elif f'단계: {args.step}' not in git('log','-1','--format=%B') and not git('log','-1','--format=%s').startswith(args.step+':'):
        raise ValueError('no new files or pending stage commit to publish')
    commit=git('rev-parse','HEAD');print('commit:',commit,flush=True)
    pending.parent.mkdir(exist_ok=True)
    pending.write_text(json.dumps({'step':args.step,'role':args.role,'branch':branch,'commit':commit,'status':'AWAITING_USER_APPROVAL'}))
    if plan and plan.get('pull_requests',{}).get('required'):
        from scripts.pull_request import render
        description=render(root,args.step,args.role,plan,value)
        print('LOCAL PR PREVIEW:',description['body_file'])
    print('AWAITING PUSH APPROVAL:',commit)
    print('Explain changes, tests and limitations to the user; publish only after explicit approval.')
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,OSError,subprocess.CalledProcessError) as error:raise SystemExit(f'BLOCKED: {error}')
