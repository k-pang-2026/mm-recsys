from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import yaml

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('team_controller',ROOT/'scripts/team.py')
team=importlib.util.module_from_spec(spec);spec.loader.exec_module(team)


def test_parallel_start_and_dependencies_are_machine_readable(tmp_path):
    plan=team.workflow(ROOT)
    assert [plan['team'][r]['name'] for r in ['A','B','C']]==['이제원','박정욱','박채영']
    for role,step in [('A','B2a'),('B','B3a'),('C','B6')]:
        assert team.select_stage(tmp_path,role,plan)==step
        assert team.dependencies(tmp_path,step,plan)==['SHARED']
    gate_dir=tmp_path/'docs/results/gates';gate_dir.mkdir(parents=True)
    (gate_dir/'SHARED.json').write_text(json.dumps({'status':'PASS'}))
    for role,step in [('A','B2a'),('B','B3a'),('C','B6')]:assert team.dependencies(tmp_path,step,plan)==[]
    (gate_dir/'B6.json').write_text(json.dumps({'status':'PASS'}))
    assert team.select_stage(tmp_path,'C',plan)=='B7'
    assert team.dependencies(tmp_path,'B7',plan)==['B5']


def test_failed_gate_is_not_skipped(tmp_path):
    plan=team.workflow(ROOT);folder=tmp_path/'docs/results/gates';folder.mkdir(parents=True)
    (folder/'B3a.json').write_text(json.dumps({'status':'FAIL'}))
    assert team.select_stage(tmp_path,'B',plan)=='B3a'
    (folder/'B3a.json').write_text(json.dumps({'status':'PASS','acceptance':'UNMEASURED'}))
    (folder/'B3b.json').write_text(json.dumps({'status':'PASS','acceptance':'FAIL'}))
    assert team.select_stage(tmp_path,'B',plan)=='B3b'
    assert team.dependencies(tmp_path,'B4',plan)==['B3b']


def test_generated_prompt_includes_validation_and_requires_push_approval():
    prompt=team.prompt('B','B3a')
    assert 'B3a' in prompt and 'docs/results/gates/B3a.json' in prompt
    assert '커밋' in prompt and '푸시' in prompt and 'publication_managed' in prompt
    assert 'config/team_workflow.yaml' in prompt
    assert '명시 승인하기 전에는 원격 푸시하지 마라' in prompt


def test_owned_configuration_overlay_cannot_change_global_seed(tmp_path,monkeypatch):
    from src.common.config import load_config
    cfg=yaml.safe_load((ROOT/'config.yaml').read_text());path=tmp_path/'config.yaml'
    path.write_text(yaml.safe_dump(cfg));(tmp_path/'config').mkdir()
    monkeypatch.setenv('SCALE','dev')
    (tmp_path/'config/search.yaml').write_text('search:\n  batch_size: 8\n')
    assert load_config(str(path))['search']['batch_size']==8
    (tmp_path/'config/search.yaml').write_text('seed: 100\n')
    import pytest
    with pytest.raises(ValueError,match='only configure'):load_config(str(path))


import pytest


@pytest.mark.parametrize('dependency_status,merged',[('PASS',True),('PASS',False),('FAIL',True)])
def test_prepare_uses_only_verified_dependencies_merged_through_main(tmp_path,dependency_status,merged):
    remote=tmp_path/'origin.git';seed=tmp_path/'seed';clone=tmp_path/'C'
    def command(*args,cwd=tmp_path):
        return subprocess.run(args,cwd=cwd,text=True,capture_output=True,check=True).stdout
    command('git','init','--bare','--initial-branch=main',str(remote))
    command('git','clone',str(remote),str(seed))
    command('git','config','user.name','Automation Fixture',cwd=seed)
    command('git','config','user.email','fixture@example.invalid',cwd=seed)
    folder=seed/'docs/results/gates';folder.mkdir(parents=True)
    (folder/'SHARED.json').write_text(json.dumps({'status':'PASS'}))
    command('git','add','docs',cwd=seed);command('git','commit','-m','common fixture',cwd=seed)
    command('git','push','origin','main',cwd=seed)
    command('git','switch','-c','feat/B/recommendation',cwd=seed)
    (folder/'B5.json').write_text(json.dumps({'status':dependency_status}))
    command('git','add','docs',cwd=seed);command('git','commit','-m','B fixture',cwd=seed)
    command('git','push','origin','feat/B/recommendation',cwd=seed)
    command('git','clone',str(remote),str(clone))
    command('git','config','user.name','Automation Fixture',cwd=clone)
    command('git','config','user.email','fixture@example.invalid',cwd=clone)
    plan=team.workflow(ROOT);team.prepare(clone,'C','B6',plan)
    (clone/'docs/results/gates/B6.json').write_text(json.dumps({'status':'PASS'}))
    command('git','add','docs',cwd=clone);command('git','commit','-m','C fixture',cwd=clone)
    command('git','push','origin','feat/C/platform',cwd=clone)
    if merged:
        command('git','switch','main',cwd=seed)
        command('git','merge','--no-edit','feat/B/recommendation',cwd=seed)
        command('git','push','origin','main',cwd=seed)
    if dependency_status=='FAIL' or not merged:
        with pytest.raises(ValueError,match='has not passed|PR not merged'):team.prepare(clone,'C','B7',plan)
        assert not (clone/'docs/results/gates/B5.json').exists()
    else:
        team.prepare(clone,'C','B7',plan)
        assert team.dependencies(clone,'B7',plan)==[]
        assert (clone/'docs/results/gates/B5.json').exists()
    assert command('git','branch','--show-current',cwd=clone).strip()=='feat/C/platform'


def test_common_and_integration_stages_never_use_main_directly():
    plan=team.workflow(ROOT)
    assert plan['stages']['SHARED']['branch']=='chore/shared-foundation'
    assert plan['stages']['INTEGRATE']['branch']=='feat/integration'
    assert plan['pull_requests']['required'] and not plan['pull_requests']['merge_requires_user_approval']
    assert plan['pull_requests']['auto_merge_when_safe']
    assert plan['push_requires_user_approval'] and not plan['auto_push']


def test_docker_handoff_requires_merged_platform_and_limits_file_ownership():
    from scripts.step_git import OWNERS
    plan=team.workflow(ROOT)
    assert all(OWNERS[step]==value['owner'] for step,value in plan['stages'].items())
    assert 'B10' in plan['order']['A'] and 'B10' not in plan['order']['C']
    assert 'WORKFLOW' not in sum(plan['order'].values(),[])
    for step in ('B9','B10','B11'):assert plan['stages'][step]['pr_ready']
    assert plan['stages']['B10']['branch']=='feat/A/docker'
    assert set(plan['stages']['B10']['requires'])=={'B2b','B5','B9'}
    assert set(plan['stages']['B11']['requires'])=={'B9','B10'}
    assert 'B10' in plan['stages']['INTEGRATE']['requires']
    def owns(role,step,path):return any(path.startswith(prefix) for prefix in team.owned_paths(plan,role,step))
    for path in ('docker/Dockerfile.api','docker-compose.yml','.dockerignore','scripts/prepare_all.sh',
                 'scripts/smoke_test.sh','tests/test_docker.py','docs/results/latency.json'):
        assert owns('A','B10',path) and not owns('C','B9',path)
    assert owns('A','B10','README.md') and owns('C','B11','README.md')
    assert not owns('A','B10','src/serving/main.py')
    assert not owns('A','B10','src/search/service.py')
    assert not owns('A','B10','scripts/train_all.py')
    assert owns('C','B9','scripts/train_all.py')
    assert owns('A','WORKFLOW','config/team_workflow.yaml')
    assert not owns('A','WORKFLOW','docker-compose.yml')


def test_docker_and_submission_handoff_in_independent_clones(tmp_path):
    """A cannot consume an unmerged B9; C cannot consume an unmerged B10."""
    remote=tmp_path/'origin.git';seed=tmp_path/'seed'
    def command(*args,cwd=tmp_path):
        return subprocess.run(args,cwd=cwd,text=True,capture_output=True,check=True).stdout
    def clone(name):
        path=tmp_path/name;command('git','clone',str(remote),str(path))
        command('git','config','user.name','Workflow Fixture',cwd=path)
        command('git','config','user.email','fixture@example.invalid',cwd=path)
        return path
    def record(path,steps):
        folder=path/'docs/results/gates';folder.mkdir(parents=True,exist_ok=True)
        for step in steps:(folder/f'{step}.json').write_text(json.dumps({'status':'PASS','acceptance':'UNMEASURED'}))
        command('git','add','docs',cwd=path);command('git','commit','-m','workflow fixture',cwd=path)
    def reviewed_merge(branch):
        command('git','fetch','origin',cwd=seed)
        command('git','merge','--no-edit',f'origin/{branch}',cwd=seed)
        command('git','push','origin','main',cwd=seed)
    command('git','init','--bare','--initial-branch=main',str(remote))
    seed=clone('seed');record(seed,['SHARED','B2a','B2b','B5'])
    command('git','push','origin','main',cwd=seed)
    a=clone('A');c=clone('C');plan=team.workflow(ROOT)
    assert team.select_stage(a,'A',plan)=='B10'
    team.prepare(c,'C','B6',plan);record(c,['B6','B7','B8','B9'])
    command('git','push','origin','feat/C/platform',cwd=c)
    assert team.select_stage(c,'C',plan)=='B11'
    with pytest.raises(ValueError,match='B9 PR not merged'):team.prepare(a,'A','B10',plan)
    assert not command('git','branch','--list','feat/A/docker',cwd=a).strip()
    reviewed_merge('feat/C/platform')
    team.prepare(a,'A','B10',plan)
    assert command('git','branch','--show-current',cwd=a).strip()=='feat/A/docker'
    assert team.dependencies(a,'B10',plan)==[]
    record(a,['B10']);command('git','push','origin','feat/A/docker',cwd=a)
    with pytest.raises(ValueError,match='B10 PR not merged'):team.prepare(c,'C','B11',plan)
    assert not (c/'docs/results/gates/B10.json').exists()
    reviewed_merge('feat/A/docker')
    team.prepare(c,'C','B11',plan)
    assert command('git','branch','--show-current',cwd=c).strip()=='feat/C/platform'
    assert team.dependencies(c,'B11',plan)==[]
    assert (c/'docs/results/gates/B10.json').exists()
    record(c,['B11']);command('git','push','origin','feat/C/platform',cwd=c)
    with pytest.raises(ValueError,match='B11 PR not merged'):team.prepare(a,'A','INTEGRATE',plan)
    reviewed_merge('feat/C/platform')
    team.prepare(a,'A','INTEGRATE',plan)
    assert command('git','branch','--show-current',cwd=a).strip()=='feat/integration'
    assert team.dependencies(a,'INTEGRATE',plan)==[]


@pytest.mark.parametrize('step,role,path,allowed',[
    ('B10','A','README.md',True),('B10','A','src/serving/main.py',False),
    ('B9','C','docker-compose.yml',False),('WORKFLOW','A','config/team_workflow.yaml',True),
    ('WORKFLOW','A','docker-compose.yml',False),
])
def test_commit_helper_enforces_stage_scope(tmp_path,monkeypatch,step,role,path,allowed):
    import scripts.step_git as helper
    plan=team.workflow(ROOT);(tmp_path/'config').mkdir()
    (tmp_path/'config/team_workflow.yaml').write_text(yaml.safe_dump(plan))
    folder=tmp_path/'docs/results/gates';folder.mkdir(parents=True)
    value={'step':step,'owner':role,'status':'PASS','scale':'dev','acceptance':'UNMEASURED',
           'commands':[{'command':'fixture validation','exit_code':0}],
           'data_fingerprint':'fixture','config_fingerprint':'fixture','evaluation_version':'fixture'}
    (folder/f'{step}.json').write_text(json.dumps(value))
    branch=plan['stages'][step].get('branch',plan['team'][role]['branch'])
    def git(*args,**kwargs):
        if args[0]=='rev-parse':return str(tmp_path)
        if args[0]=='branch':return branch
        if args[0]=='remote':return plan['repository']
        return ''
    monkeypatch.chdir(tmp_path);monkeypatch.setattr(helper,'git',git)
    monkeypatch.setattr(helper,'discover_files',lambda root:[path,f'docs/results/gates/{step}.json'])
    monkeypatch.setattr(sys,'argv',['step_git.py','--step',step,'--role',role,'--mode','check'])
    if allowed:assert helper.main()==0
    else:
        with pytest.raises(ValueError,match='ownership'):helper.main()


def test_old_c_docker_assignment_is_rejected_before_git_access(monkeypatch):
    import scripts.step_git as helper
    monkeypatch.setattr(sys,'argv',['step_git.py','--step','B10','--role','C','--mode','check'])
    monkeypatch.setattr(helper,'git',lambda *args,**kwargs:pytest.fail('incorrect role must fail before Git access'))
    with pytest.raises(ValueError,match='owner is A'):helper.main()
