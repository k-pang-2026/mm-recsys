from __future__ import annotations

import json
import base64
from pathlib import Path
import pytest
from scripts.pull_request import ensure, render, merge_reviewed, auto_merge


class FakeAPI:
    repo='k-pang-2026/mm-recsys'
    def __init__(self,existing=False):
        self.calls=[]
        self.pr={'number':1,'html_url':'https://github.com/k-pang-2026/mm-recsys/pull/1','node_id':'fixture',
                 'head':{'sha':'a'*40,'ref':'feat/B/recommendation'},'base':{'ref':'main'},'draft':True} if existing else None
    def request(self,method,path,payload=None):
        self.calls.append((method,path,payload))
        if method=='GET' and '?' in path:return [self.pr] if self.pr else []
        if method=='POST' and path=='/graphql':self.pr['draft']=False;return {'data':{'markPullRequestReadyForReview':{'pullRequest':{'isDraft':False}}}}
        if method=='POST':
            self.pr={'number':1,'html_url':'https://github.com/k-pang-2026/mm-recsys/pull/1','node_id':'fixture',
                     'head':{'sha':'a'*40,'ref':payload['head']},'base':{'ref':payload['base']},'draft':payload['draft']}
        return self.pr


def description(tmp_path,draft):
    body=tmp_path/'body.md';body.write_text('실제 구현 변경과 검증 근거\n')
    return {'head':'feat/B/recommendation','base':'main','commit':'a'*40,'title':'feat(recommendation): 추천 구현',
            'body_file':'body.md','draft':draft}


def test_creates_one_pr_and_keeps_multiline_korean_body(tmp_path):
    client=FakeAPI();result=ensure(tmp_path,description(tmp_path,True),client)
    assert result['draft'] and result['commit']=='a'*40
    create=[c for c in client.calls if c[0]=='POST']
    assert len(create)==1 and create[0][2]['body'].endswith('\n')
    assert '검증 근거' in create[0][2]['body']
    assert json.loads((tmp_path/'.team/pr/publication.json').read_text())['number']==1
    assert all('merge' not in path for _,path,_ in client.calls)


def test_updates_existing_pr_and_marks_completed_feature_ready(tmp_path):
    client=FakeAPI(existing=True);result=ensure(tmp_path,description(tmp_path,False),client)
    assert result['draft'] is False
    assert any(method=='PATCH' for method,_,_ in client.calls)
    assert any(path=='/graphql' for _,path,_ in client.calls)
    assert not any(method=='POST' and path.endswith('/pulls') for method,path,_ in client.calls)


def test_pr_with_wrong_commit_is_not_reported_as_verified(tmp_path):
    client=FakeAPI(existing=True);client.pr['head']['sha']='b'*40
    with pytest.raises(ValueError,match='approved commit'):ensure(tmp_path,description(tmp_path,True),client)
    assert not (tmp_path/'.team/pr/publication.json').exists()


class MergeAPI:
    repo='k-pang-2026/mm-recsys'
    def __init__(self):
        self.calls=[]
        self.pr={'state':'open','draft':False,'head':{'sha':'a'*40,'ref':'feat/B/recommendation'},
                 'base':{'ref':'main','sha':'c'*40},'title':'feat(recommendation): 추천 모델 구현','html_url':'fixture',
                 'mergeable':True,'mergeable_state':'clean'}
        self.checks=[{'name':'common','status':'completed','conclusion':'success'}]
        self.reviews=[]
        self.gate={'step':'B5','owner':'B','status':'PASS','scale':'dev','acceptance':'UNMEASURED',
                   'commands':[{'command':'fixture check','exit_code':0}],'data_fingerprint':'fixture-data',
                   'config_fingerprint':'fixture-config','evaluation_version':'fixture-v1'}
        self.move_base=False
        self.move_head=False
    def request(self,method,path,payload=None):
        self.calls.append((method,path,payload))
        if method=='PUT':return {'merged':True,'sha':'b'*40}
        if '/contents/' in path:return {'encoding':'base64','content':base64.b64encode(json.dumps(self.gate).encode()).decode()}
        if 'check-runs?' in path:return {'check_runs':self.checks,'total_count':len(self.checks)}
        if path.endswith('/status'):return {'total_count':0,'state':'pending'}
        if '/reviews?' in path:
            if self.move_base:self.pr['base']['sha']='d'*40
            if self.move_head:self.pr['head']['sha']='e'*40
            return self.reviews
        return self.pr


def merge_plan():
    return {'pull_requests':{'base':'main','required_ci_check':'common','merge_method':'merge'},
            'stages':{'B5':{'pr_ready':True}},'team':{'B':{'branch':'feat/B/recommendation'}}}


def test_merge_checks_exact_reviewed_sha_ci_and_reviews_before_put():
    client=MergeAPI()
    client.reviews=[{'state':'CHANGES_REQUESTED','user':{'login':'reviewer'}},
                    {'state':'APPROVED','user':{'login':'reviewer'}}]
    result=merge_reviewed(client,merge_plan(),'B5','B',1,'a'*40)
    assert result['merged'] and result['sha']=='b'*40
    assert client.calls[-1][0]=='PUT'
    assert client.calls[-1][2]['sha']=='a'*40
    assert client.calls[-1][2]['merge_method']=='merge'
    assert '검증·리뷰' in client.calls[-1][2]['commit_message']


@pytest.mark.parametrize('problem',['changed_sha','draft','failing_ci','pending_ci','review_changes','incomplete_stage','invalid_title',
                                    'conflict','mergeable_unknown','protected','failed_quality','failed_gate','wrong_owner','moved_base','moved_head'])
def test_merge_refuses_unreviewed_head_or_incomplete_checks(problem):
    client=MergeAPI();plan=merge_plan()
    if problem=='changed_sha':client.pr['head']['sha']='b'*40
    elif problem=='draft':client.pr['draft']=True
    elif problem=='failing_ci':client.checks[0]['conclusion']='failure'
    elif problem=='pending_ci':client.checks.append({'name':'lint','status':'in_progress','conclusion':None})
    elif problem=='review_changes':client.reviews=[{'state':'CHANGES_REQUESTED','user':{'login':'reviewer'}}]
    elif problem=='invalid_title':client.pr['title']='추천 개발 완료'
    elif problem=='conflict':client.pr['mergeable']=False
    elif problem=='mergeable_unknown':client.pr['mergeable']=None
    elif problem=='protected':client.pr['mergeable_state']='blocked'
    elif problem=='failed_quality':client.gate['acceptance']='FAIL'
    elif problem=='failed_gate':client.gate['status']='FAIL'
    elif problem=='wrong_owner':client.gate['owner']='A'
    elif problem=='moved_base':client.move_base=True
    elif problem=='moved_head':client.move_head=True
    else:plan['stages']['B5']['pr_ready']=False
    with pytest.raises(ValueError):merge_reviewed(client,plan,'B5','B',1,'a'*40)
    assert not any(c[0]=='PUT' for c in client.calls)


def test_cli_merge_without_permission_or_policy_never_reads_credentials(tmp_path,monkeypatch):
    import scripts.pull_request as pr
    import yaml
    plan=merge_plan();plan['stages']['B5']['owner']='B'
    (tmp_path/'config').mkdir();(tmp_path/'config/team_workflow.yaml').write_text(yaml.safe_dump(plan))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr('sys.argv',['pull_request.py','--step','B5','--role','B','--merge','1','--commit','a'*40])
    def forbidden(*args):raise AssertionError('credentials read before permission')
    monkeypatch.setattr(pr,'GitHubAPI',forbidden)
    with pytest.raises(ValueError,match='explicit PR merge approval'):pr.main()


def auto_plan():
    plan=merge_plan();plan['pull_requests'].update(auto_merge_when_safe=True,merge_requires_user_approval=False)
    return plan


def test_automatic_merge_updates_publication_and_clears_pending(tmp_path):
    folder=tmp_path/'.team/pr';folder.mkdir(parents=True)
    (folder/'publication.json').write_text(json.dumps({'number':1,'commit':'a'*40,'merged':False}))
    result=auto_merge(tmp_path,MergeAPI(),auto_plan(),'B5','B',1,'a'*40)
    assert result['merged'] and not (folder/'merge_pending.json').exists()
    assert json.loads((folder/'publication.json').read_text())['merge_sha']=='b'*40


def test_automatic_merge_waits_for_ci_before_write(tmp_path,monkeypatch):
    import scripts.pull_request as pr
    client=MergeAPI();client.checks[0].update(status='in_progress',conclusion=None)
    sleeps=[]
    def finish_ci(seconds):
        pending=json.loads((tmp_path/'.team/pr/merge_pending.json').read_text())
        assert pending['status']=='WAITING' and pending['commit']=='a'*40
        assert not any(c[0]=='PUT' for c in client.calls)
        sleeps.append(seconds);client.checks[0].update(status='completed',conclusion='success')
    monkeypatch.setattr(pr.time,'sleep',finish_ci)
    result=auto_merge(tmp_path,client,auto_plan(),'B5','B',1,'a'*40,wait=True)
    assert result['merged'] and len(sleeps)==1


@pytest.mark.parametrize('problem',['ci_pending','conflict'])
def test_automatic_merge_preserves_retry_state_without_unsafe_write(tmp_path,problem):
    client=MergeAPI()
    if problem=='ci_pending':client.checks[0].update(status='in_progress',conclusion=None)
    else:client.pr['mergeable']=False
    result=auto_merge(tmp_path,client,auto_plan(),'B5','B',1,'a'*40)
    assert result['status']==('WAITING' if problem=='ci_pending' else 'BLOCKED')
    assert (tmp_path/'.team/pr/merge_pending.json').exists()
    assert not any(c[0]=='PUT' for c in client.calls)


def test_automatic_merge_requires_explicit_project_policy(tmp_path):
    client=MergeAPI()
    with pytest.raises(ValueError,match='not authorized'):auto_merge(tmp_path,client,merge_plan(),'B5','B',1,'a'*40)
    assert client.calls==[]


def test_merge_retry_accepts_already_merged_same_commit_without_second_write():
    client=MergeAPI();client.pr.update(state='closed',merged=True,merge_commit_sha='b'*40)
    result=merge_reviewed(client,merge_plan(),'B5','B',1,'a'*40)
    assert result['merged'] and not any(c[0]=='PUT' for c in client.calls)


def test_cli_merge_uses_authorized_policy_without_new_confirmation(tmp_path,monkeypatch):
    import scripts.pull_request as pr
    import yaml
    plan=auto_plan();plan['stages']['B5']['owner']='B'
    (tmp_path/'config').mkdir();(tmp_path/'config/team_workflow.yaml').write_text(yaml.safe_dump(plan))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr('sys.argv',['pull_request.py','--step','B5','--role','B','--merge','1','--commit','a'*40])
    monkeypatch.setattr(pr,'GitHubAPI',lambda root,plan:MergeAPI())
    pr.main()
    assert json.loads((tmp_path/'.team/pr/merge_result.json').read_text())['merged']


def test_preview_is_local_and_contains_quality_limits(tmp_path,monkeypatch):
    import scripts.pull_request as pr
    def git(root,*args):
        if args[0]=='branch':return 'feat/B/recommendation'
        if args[0]=='rev-parse':return 'a'*40
        return 'src/recommendation/two_tower.py\ntests/test_two_tower.py'
    monkeypatch.setattr(pr,'git',git)
    plan={'pull_requests':{'base':'main','auto_merge_when_safe':True,'merge_requires_user_approval':False},
          'stages':{'B3a':{'pr_ready':False}},'team':{'B':{'name':'박정욱'}}}
    gate={'commands':[{'command':'검사 fixture','exit_code':0}],'acceptance':'UNMEASURED','status':'PASS','scale':'dev','data_fingerprint':'fixture'}
    info=render(tmp_path,'B3a','B',plan,gate)
    assert info['draft'] and info['base']=='main'
    text=(tmp_path/info['body_file']).read_text()
    assert '미측정' in text and '박정욱' in text and '자동 병합' in text
    assert not (tmp_path/'.team/pr/publication.json').exists()
