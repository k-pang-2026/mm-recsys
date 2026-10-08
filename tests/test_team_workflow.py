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
