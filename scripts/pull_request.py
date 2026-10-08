"""Render PRs locally; publish only through the explicitly approved stage publisher."""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
import yaml
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


TITLES={'SHARED':'chore(shared): 공통 개발환경과 3인 병렬 개발 기반 구성',
        'INTEGRATE':'chore(integration): 검색·추천·서빙 통합 검증 완료'}


def git(root: Path,*args: str) -> str:
    return subprocess.check_output(['git',*args],cwd=root,text=True).strip()


def render(root: Path,step: str,role: str,plan: dict,value: dict) -> dict:
    branch=git(root,'branch','--show-current');base=plan['pull_requests']['base']
    if branch==base:raise ValueError('main must be updated through a feature PR')
    commit=git(root,'rev-parse','HEAD')
    titles={'A':'feat(search): 멀티모달 검색 구현','B':'feat(recommendation): 다단계 추천 구현','C':'feat(platform): 서빙·평가·운영 환경 구현'}
    title=TITLES.get(step,titles[role])
    if (step=='SHARED' and value.get('commit_summary_ko')
            and git(root,'ls-tree','--name-only',f'origin/{base}','--','docs/results/gates/SHARED.json')):
        title='chore(shared): '+value['commit_summary_ko']
    files=git(root,'diff','--name-only',f'origin/{base}...HEAD').splitlines()
    checks='\n'.join(f"- 종료 코드 {c['exit_code']}: `{c['command']}`" for c in value['commands'])
    quality={'UNMEASURED':'미측정','FAIL':'미달','PASS':'통과'}[value['acceptance']]
    draft=not plan['stages'][step].get('pr_ready',False) or value['acceptance']=='FAIL'
    extra=[]
    readiness=root/'docs/results/common_readiness.json'
    if step=='SHARED' and readiness.exists():
        info=json.loads(readiness.read_text())
        extra=['공통 설정·데이터·API 계약과 실행 도구를 제공하여 세 팀원이 독립 클론에서 병렬 개발할 수 있게 합니다.',
               f"회귀 검사: {info['tests']['passed']}개 통과. Docker 상태: {info['docker']['status']}.",
               '검색·추천 모델과 Redis/CT/전체 Docker 실행은 후속 담당 단계에서 구현·측정합니다.']
    body='\n'.join([f"이번 변경: {value.get('commit_summary_ko',title)}",*extra,'',f"담당: {plan['team'][role]['name']} ({role}) / 최근 완료 단계: {step}",
                    f'대상: `{branch}` → `{base}` / 변경 파일: {len(files)}개',
                    f'검토할 커밋: `{commit}`','', '검증 결과:',checks,
                    f"구조: {value['status']} / 규모: {value['scale']} / 최종 종합 품질: {quality}",
                    f"근거: `docs/results/gates/{step}.json` / 데이터: `{value['data_fingerprint']}`",'',
                    '중간 단계는 Draft로 유지하고 기능 완료 시 검토 준비 상태로 전환합니다.',
                    ('main 직접 푸시는 하지 않습니다. 충돌·CI·품질·필수 리뷰 조건을 확인해 안전한 PR은 자동 병합합니다.'
                     if automatic_merge_enabled(plan) else 'main 직접 푸시는 하지 않습니다. CI와 리뷰를 확인하고 별도 병합 허가 후에만 병합합니다.'),''])
    folder=root/'.team/pr';folder.mkdir(parents=True,exist_ok=True)
    path=folder/f'{step}.md';path.write_text(body,encoding='utf-8')
    result={'step':step,'role':role,'base':base,'head':branch,'commit':commit,'title':title,'body_file':str(path.relative_to(root)),'draft':draft}
    (folder/f'{step}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError('GitHub API redirects are not followed with authentication')


class GitHubAPI:
    def __init__(self,root: Path,plan: dict) -> None:
        self.root=root
        self.repo=plan['repository'].split('github.com/',1)[1].removesuffix('.git')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',self.repo):raise ValueError('invalid GitHub repository')
        self.timeout=plan['pull_requests'].get('timeout_seconds',30)
        self.version=plan['pull_requests'].get('api_version','2026-03-10')
        self._token=os.getenv('GH_TOKEN') or os.getenv('GITHUB_TOKEN')
        if not self._token:
            # Reuse the user's Git authentication; never print/store credential output.
            credential=subprocess.run(['git','credential','fill'],cwd=root,text=True,capture_output=True,
                input=f'protocol=https\nhost=github.com\npath={self.repo}.git\n\n',
                env={**os.environ,'GIT_TERMINAL_PROMPT':'0'},timeout=self.timeout)
            if credential.returncode:raise ValueError('GitHub API authentication unavailable; finish existing GitHub login, then retry the same approved commit')
            fields=dict(line.split('=',1) for line in credential.stdout.splitlines() if '=' in line)
            self._token=fields.get('password') or fields.get('credential')
        if not self._token:raise ValueError('GitHub authentication must provide API access; do not place tokens in chat or repository')
        self._opener=build_opener(NoRedirect())

    def request(self,method: str,path: str,payload: dict | None = None):
        request=Request('https://api.github.com'+path,method=method,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={'Accept':'application/vnd.github+json','Content-Type':'application/json',
                     'Authorization':'Bearer '+self._token,'X-GitHub-Api-Version':self.version,'User-Agent':'mm-recsys-workflow'})
        try:
            with self._opener.open(request,timeout=self.timeout) as response:return json.load(response)
        except HTTPError as error:
            raise ValueError(f'GitHub API {method} failed with HTTP {error.code}; verify repository/PR permissions and retry; credentials are not logged') from None

    def preflight(self) -> None:
        self.request('GET',f'/repos/{self.repo}')


def ensure(root: Path,description: dict,client: GitHubAPI) -> dict:
    owner=client.repo.split('/',1)[0]
    query=urlencode({'state':'open','head':f"{owner}:{description['head']}",'base':description['base']})
    path=f'/repos/{client.repo}/pulls'
    existing=client.request('GET',path+'?'+query)
    payload={'title':description['title'],'body':(root/description['body_file']).read_text(encoding='utf-8')}
    if existing:
        pr=existing[0]
        pr=client.request('PATCH',path+f"/{pr['number']}",payload)
        if pr['draft'] and not description['draft']:
            updated=client.request('POST','/graphql',{'query':'mutation($id:ID!){markPullRequestReadyForReview(input:{pullRequestId:$id}){pullRequest{isDraft}}}',
                                                    'variables':{'id':pr['node_id']}})
            if updated.get('errors'):raise ValueError('GitHub could not mark the existing Draft PR ready; retry after verifying permissions')
            pr=client.request('GET',path+f"/{pr['number']}")
        elif not pr['draft'] and description['draft']:
            raise ValueError('existing PR is ready but this stage is incomplete; restore Draft status and review before merging')
    else:
        pr=client.request('POST',path,{**payload,'head':description['head'],'base':description['base'],'draft':description['draft']})
    if pr['head']['sha']!=description['commit'] or pr['head']['ref']!=description['head'] or pr['base']['ref']!=description['base'] or pr['draft']!=description['draft']:
        raise ValueError('PR does not reference the approved commit/branches; retry after remote synchronization')
    result={'number':pr['number'],'url':pr['html_url'],'commit':description['commit'],'head':description['head'],
            'base':description['base'],'draft':pr['draft'],'merged':False}
    folder=root/'.team/pr';folder.mkdir(parents=True,exist_ok=True)
    (folder/'publication.json').write_text(json.dumps(result,indent=2))
    return result


class MergeNotReady(ValueError):
    def __init__(self,message: str,*,retryable: bool = False):
        super().__init__(message)
        self.retryable=retryable


def automatic_merge_enabled(plan: dict) -> bool:
    policy=plan.get('pull_requests',{})
    return policy.get('auto_merge_when_safe') is True and policy.get('merge_requires_user_approval') is False


def merge_reviewed(client: GitHubAPI,plan: dict,step: str,role: str,number: int,sha: str) -> dict:
    """Verify the exact published commit; GitHub additionally enforces repository protections."""
    if not re.fullmatch('[0-9a-f]{40}',sha):raise ValueError('reviewed full commit SHA required')
    if not plan['stages'][step].get('pr_ready',False):raise ValueError('complete the feature before approving its PR merge')
    path=f'/repos/{client.repo}/pulls/{number}'
    pr=client.request('GET',path)
    expected=plan['stages'][step].get('branch',plan['team'][role]['branch'])
    if (pr['head']['sha']!=sha or pr['head']['ref']!=expected
            or pr['base']['ref']!=plan['pull_requests']['base']):
        raise ValueError('PR state/branches/head differ from the reviewed merge approval')
    if pr.get('merged'):
        return {'number':number,'merged':True,'sha':pr['merge_commit_sha'],'url':pr['html_url']}
    if pr['state']!='open' or pr['draft']:raise MergeNotReady('PR must be open and ready')
    if pr.get('mergeable') is False:raise MergeNotReady('PR has merge conflicts; resolve and revalidate first')
    base_sha=pr['base']['sha']
    from scripts.step_git import check_gate
    content=client.request('GET',f'/repos/{client.repo}/contents/docs/results/gates/{step}.json?ref={sha}')
    if content.get('encoding')!='base64':raise ValueError('remote gate encoding unsupported')
    gate=json.loads(base64.b64decode(content['content']))
    check_gate(gate,step,role)
    if gate['acceptance']=='FAIL':raise MergeNotReady('published stage quality gate failed; do not merge')
    if (not re.fullmatch(r'(feat|fix|test|docs|chore)\((shared|search|recommendation|platform|ct|docker|integration|sync)\): [^\r\n]+',pr['title'])
            or not re.search('[가-힣]',pr['title']) or len(pr['title'])>72):
        raise ValueError('PR/merge title must follow the common Korean Conventional Commit rule')
    checks=[];page=1
    while True:
        result=client.request('GET',f'/repos/{client.repo}/commits/{sha}/check-runs?filter=latest&per_page=100&page={page}')
        checks.extend(result['check_runs'])
        if len(checks)>=result['total_count']:break
        if not result['check_runs']:raise ValueError('incomplete CI check pagination')
        page+=1
    required=plan['pull_requests']['required_ci_check']
    if any(c['status']=='completed' and c['conclusion'] not in ('success','neutral','skipped') for c in checks):
        raise MergeNotReady('CI is failing; do not merge')
    if any(c['status']!='completed' for c in checks) or not any(c['name']==required for c in checks):
        raise MergeNotReady('CI is pending; wait for the published commit',retryable=True)
    if not any(c['name']==required and c['conclusion']=='success' for c in checks):
        raise MergeNotReady('required common CI has not passed on the published commit')
    status=client.request('GET',f'/repos/{client.repo}/commits/{sha}/status')
    if status.get('total_count',0) and status.get('state')!='success':
        raise MergeNotReady('commit status checks are not passing',retryable=status.get('state')=='pending')
    reviews=[];page=1
    while True:
        batch=client.request('GET',path+f'/reviews?per_page=100&page={page}')
        reviews.extend(batch)
        if len(batch)<100:break
        page+=1
    latest={}
    for review in reviews:
        if review['state'] in ('APPROVED','CHANGES_REQUESTED','DISMISSED'):latest[review['user']['login']]=review['state']
    if 'CHANGES_REQUESTED' in latest.values():raise MergeNotReady('unresolved requested changes; finish review before merge')
    # Recheck both branches immediately before the write, after checking CI and reviews.
    fresh=client.request('GET',path)
    if (fresh['head']['sha']!=sha or fresh['head']['ref']!=expected or fresh['base']['sha']!=base_sha
            or fresh['base']['ref']!=plan['pull_requests']['base'] or fresh['state']!='open' or fresh['draft']):
        raise MergeNotReady('PR head/base/state changed during verification; synchronize and revalidate')
    if fresh.get('mergeable') is None or fresh.get('mergeable_state')=='unknown':
        raise MergeNotReady('GitHub is calculating mergeability',retryable=True)
    if fresh.get('mergeable') is not True or fresh.get('mergeable_state')!='clean':
        raise MergeNotReady('PR is not cleanly mergeable; preserve branch protections and review requirements')
    result=client.request('PUT',path+'/merge',{'sha':sha,'merge_method':plan['pull_requests']['merge_method'],
                           'commit_title':pr['title'],'commit_message':f'PR #{number}의 검증·리뷰 확인 후 병합\n승인한 커밋: {sha}'})
    if not result.get('merged'):raise ValueError('GitHub did not merge the PR; keep protections and report the actual condition')
    return {'number':number,'merged':True,'sha':result['sha'],'url':pr['html_url']}


def auto_merge(root: Path,client: GitHubAPI,plan: dict,step: str,role: str,number: int,sha: str,*,wait: bool = False) -> dict:
    if not automatic_merge_enabled(plan):raise ValueError('automatic merge is not authorized by project policy')
    folder=root/'.team/pr';folder.mkdir(parents=True,exist_ok=True)
    pending=folder/'merge_pending.json'
    state={'step':step,'role':role,'number':number,'commit':sha,'status':'WAITING_FOR_SAFE_MERGE'}
    pending.write_text(json.dumps(state,ensure_ascii=False,indent=2))
    policy=plan['pull_requests'];deadline=time.monotonic()+policy.get('merge_wait_seconds',600)
    while True:
        try:result=merge_reviewed(client,plan,step,role,number,sha)
        except ValueError as error:
            retryable=isinstance(error,MergeNotReady) and error.retryable
            state.update(status='WAITING' if retryable else 'BLOCKED',reason=str(error))
            pending.write_text(json.dumps(state,ensure_ascii=False,indent=2))
            if not wait or not retryable or time.monotonic()>=deadline:
                print('AUTO MERGE DEFERRED:',state['reason'],flush=True)
                return state
            print('AUTO MERGE WAIT:',state['reason'],flush=True)
            time.sleep(min(policy.get('merge_poll_seconds',10),max(0,deadline-time.monotonic())))
            continue
        (folder/'merge_result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        published=folder/'publication.json'
        if published.exists():
            publication=json.loads(published.read_text())
            if publication['number']==number and publication['commit']==sha:
                publication.update(merged=True,merge_sha=result['sha'])
                published.write_text(json.dumps(publication,ensure_ascii=False,indent=2))
        pending.unlink(missing_ok=True)
        print('AUTO MERGE VERIFIED:',result['url'],result['sha'],flush=True)
        return result


def main() -> None:
    parser=argparse.ArgumentParser(description='Generate a local Korean PR preview without pushing or creating a remote PR')
    parser.add_argument('--step',required=True);parser.add_argument('--role',required=True,choices=['A','B','C'])
    parser.add_argument('--merge',type=int);parser.add_argument('--approved',action='store_true');parser.add_argument('--commit')
    parser.add_argument('--wait',action='store_true',help='wait a bounded time for pending CI/mergeability')
    args=parser.parse_args();root=Path.cwd();plan=yaml.safe_load((root/'config/team_workflow.yaml').read_text())
    if plan['stages'][args.step]['owner']!=args.role:raise ValueError('stage/owner mismatch')
    if args.merge is not None:
        if not args.commit or not (args.approved or automatic_merge_enabled(plan)):
            raise ValueError('explicit PR merge approval or authorized automatic-merge policy and exact commit SHA required')
        client=GitHubAPI(root,plan)
        if automatic_merge_enabled(plan):
            result=auto_merge(root,client,plan,args.step,args.role,args.merge,args.commit,wait=args.wait)
        else:result=merge_reviewed(client,plan,args.step,args.role,args.merge,args.commit)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        if not result.get('merged'):raise SystemExit(2)
        return
    value=json.loads((root/f'docs/results/gates/{args.step}.json').read_text())
    print(json.dumps(render(root,args.step,args.role,plan,value),ensure_ascii=False,indent=2))


if __name__=='__main__':
    try:main()
    except (ValueError,OSError,subprocess.CalledProcessError) as error:raise SystemExit(f'BLOCKED: {error}')
