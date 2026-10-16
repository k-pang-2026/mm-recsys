"""Submission checks must reject altered evidence and retain incomplete scope."""
from __future__ import annotations

import json
import copy
from pathlib import Path
import shutil
import subprocess

import httpx
import pytest

from scripts import check_submission as checker
from scripts.check_submission_evidence import (QUALITY, SMOKE, assemble_acceptance, audit_python,
                                               check_hashes, collect_integration_checks, collect_quality, read_json)
from src.common.artifacts import file_hash

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def evidence(tmp_path):
    quality = read_json(ROOT, QUALITY)
    frozen = read_json(ROOT, 'docs/results/docker/quality_selection_full.json')
    names = {QUALITY, SMOKE, 'docs/results/docker/quality_full_valid.json',
             'docs/results/docker/quality_selection_full.json', frozen['source'],
             'docs/results/docker/verified_full.json', 'docs/results/ab_test.json',
             'docs/results/ct_dev_fixture.json'}
    names |= set(quality['identity']['source_hashes']) | set(quality['identity']['docker_sources'])
    measured_commit = subprocess.check_output(['git', 'log', '-1', '--format=%H', '--', QUALITY],
                                              cwd=ROOT, text=True).strip()
    measured_sources = set(quality['identity']['source_hashes']) | set(quality['identity']['docker_sources'])
    for name in names:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        if name in measured_sources:
            # This fixture audits immutable B10 measurements against their original
            # sources, while current-source integration is measured separately.
            (tmp_path / name).write_bytes(subprocess.check_output(
                ['git', 'show', f'{measured_commit}:{name}'], cwd=ROOT))
        else:
            shutil.copyfile(ROOT / name, tmp_path / name)
    return tmp_path


@pytest.mark.parametrize('defect', ['row_value', 'below_target', 'raw_http', 'dev', 'source', 'freeze', 'coverage'])
def test_altered_measurement_cannot_be_aggregated(evidence, defect):
    quality = read_json(evidence, QUALITY)
    if defect == 'row_value':
        quality['metrics'][0]['value'] = 1.0
    elif defect == 'below_target':
        quality['search']['primary']['mrr'] = 0.1
    elif defect == 'raw_http':
        quality['api']['modes']['text']['http_samples_ms'][0] = float('nan')
    elif defect == 'dev':
        quality['scale'] = 'dev'
    elif defect == 'source':
        (evidence / next(iter(quality['identity']['source_hashes']))).write_text('changed')
    elif defect == 'freeze':
        frozen = read_json(evidence, 'docs/results/docker/quality_selection_full.json')
        (evidence / frozen['source']).write_text('{}')
    else:
        quality['recommendation']['metrics']['full_pipeline']['coverage_users'] -= 1
    (evidence / QUALITY).write_text(json.dumps(quality))
    with pytest.raises(ValueError):
        collect_quality(evidence, checker.full_config())


def test_dev_ab_and_fixture_ct_never_become_full_acceptance(evidence):
    (evidence / 'submission.json').write_text(json.dumps(dict(readiness_status='BLOCKED', blockers=['pending'])))
    result = assemble_acceptance(evidence, checker.full_config(), 'submission.json')
    assert result['status'] == 'UNMEASURED'
    assert result['checks']['ab_statistics']['status'] == 'UNMEASURED'
    assert result['checks']['ct_retrain_and_rollback']['status'] == 'UNMEASURED'
    assert result['checks']['docker_reproduction']['exit_code'] is None
    assert result['checks']['submission']['status'] == 'BLOCKED'
    assert all(row['status'] == 'PASS' for row in result['metrics'].values())


def test_evidence_cannot_escape_checkout_by_path_or_symlink(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    (tmp_path / 'outside.json').write_text('{}')
    (root / 'link.json').symlink_to(tmp_path / 'outside.json')
    for name in ('../outside.json', 'link.json', str(tmp_path / 'outside.json')):
        with pytest.raises(ValueError, match='escapes'):
            read_json(root, name)
        with pytest.raises(ValueError, match='invalid'):
            check_hashes(root, {name: 'unused'})


def test_ast_audit_reports_untyped_args_constant_seed_and_config_seed(tmp_path):
    (tmp_path / 'source.py').write_text('''
def untyped(x, /, *, y):
    set_seed(cfg['seed'])
    seed = 17
    return x
''')
    audit = audit_python(tmp_path, ['source.py'], ['seed'])
    assert audit['missing_annotations'][0]['missing'] == ['x', 'y', 'return']
    assert audit['suspected_settings'][0]['value'] == 17
    assert audit['seed_calls'][0]['call'] == "set_seed(cfg['seed'])"


def test_unavailable_live_api_is_blocked(monkeypatch):
    def unavailable(*args, **kwargs):
        raise httpx.ConnectError('unavailable')
    monkeypatch.setattr(httpx.Client, 'get', unavailable)
    assert checker.live_check('http://127.0.0.1:1')['status'] == 'BLOCKED'


def test_final_readiness_has_distinct_nonzero_exit(monkeypatch):
    monkeypatch.setattr(checker, 'verify_saved', lambda root: dict(
        delivery_status='PASS', readiness_status='BLOCKED', blockers=['full CT unmeasured']))
    monkeypatch.setattr('sys.argv', ['check_submission.py', '--verify-existing', '--require-ready'])
    assert checker.main() == 2


def test_full_config_does_not_change_caller_scale(monkeypatch):
    import os
    monkeypatch.setenv('SCALE', 'dev')
    assert checker.full_config()['scale'] == 'full'
    assert os.environ['SCALE'] == 'dev'


@pytest.mark.parametrize('scenario', ['dev_ab', 'small_ab', 'reused_clone', 'retained_ct', 'missing_session'])
def test_pass_receipt_cannot_hide_incomplete_integration_execution(tmp_path, scenario):
    required = ['docker_reproduction', 'api_schemas', 'ab_statistics', 'session_response', 'ct_retrain_and_rollback']
    measured = dict(status='PASS', scale='full', data_fingerprint='dataset')
    name = 'ab_statistics'
    if scenario == 'dev_ab':
        measured['scale'] = 'dev'
    elif scenario == 'small_ab':
        experiment = dict(scale='full', status='PASS', days=30, top_n=10,
                          identity=dict(data_fingerprint='dataset'),
                          arms={arm: dict(users=200) for arm in ('control', 'treatment')})
        (tmp_path / 'ab.json').write_text(json.dumps(experiment))
        measured.update(source='ab.json', sha256=file_hash(tmp_path / 'ab.json'))
    elif scenario == 'reused_clone':
        name = 'docker_reproduction'
        measured.update(initial_data_files=1, initial_model_files=0, prepared_data_and_models_from_empty=True)
    elif scenario == 'retained_ct':
        name = 'ct_retrain_and_rollback'
        measured.update(real_reload_and_rollback=False, checks=dict(full_three_model_retraining=True))
    else:
        name = 'session_response'
        measured.update(checks=dict(live_redis_mab='PASS', max_reward='PASS', dedup_feedback='PASS'))
    (tmp_path / 'measured.json').write_text(json.dumps(measured))
    entry = dict(source='measured.json', sha256=file_hash(tmp_path / 'measured.json'), status='UNMEASURED', exit_code=None)
    execution = dict(data_fingerprint='dataset', checks={key: dict(entry) for key in required})
    execution['checks'][name].update(status='PASS', exit_code=0)
    with pytest.raises(ValueError):
        collect_integration_checks(tmp_path, execution, 'dataset')


def test_lossless_ab_archive_reconstructs_verified_bytes_and_rejects_tampering(tmp_path, monkeypatch):
    from scripts import archive_integration_ab as packer
    from scripts.check_submission_evidence import read_ab_evidence
    from src.common.artifacts import write_json
    monkeypatch.setattr(packer, 'ROOT', tmp_path)
    report = dict(status='PASS', scale='full', run_id='measured-run',
                  arms={arm: dict(users=5000, arm_statistics={'u:p': dict(exposures=2, reward=.2)},
                                  unattributed_feedback=0) for arm in ('control', 'treatment')})
    write_json(tmp_path / 'original.json', report)
    digest = file_hash(tmp_path / 'original.json')
    write_json(tmp_path / 'verification.json', dict(status='PASS', scale='full', run_id='measured-run', sha256=digest))
    packer.archive('original.json', 'verification.json', 'archive.json')
    assert read_ab_evidence(tmp_path, 'archive.json') == report
    assert file_hash(tmp_path / 'raw/original.json') == digest
    packed = read_json(tmp_path, 'archive.json')
    shard = packed['arm_statistics_shards']['treatment'][0]
    write_json(tmp_path / shard['source'], {'u:p': dict(exposures=2, reward=2.)})
    # Even replacing the shard hash cannot hide a change to the measured report.
    shard['sha256'] = file_hash(tmp_path / shard['source'])
    write_json(tmp_path / 'archive.json', packed)
    with pytest.raises(ValueError, match='differs from measured original'):
        read_ab_evidence(tmp_path, 'archive.json')


def test_artifact_aliases_cannot_change_measured_model_or_generator_recipe(tmp_path):
    from scripts.check_submission_evidence import validate_configuration
    from src.common.artifacts import fingerprint, write_json
    from src.simulator.generate import generation_identity
    measured = checker.full_config()
    write_json(tmp_path / 'integration/configuration_full.json', measured)
    quality = dict(identity=dict(config_fingerprint=fingerprint(measured)),
                   data_fingerprint=fingerprint(generation_identity(measured)))
    alias = copy.deepcopy(measured)
    alias['paths']['data_dir'] = 'data/other-local-alias'
    alias['redis']['host'] = '127.0.0.1'
    validate_configuration(tmp_path, alias, quality, 'integration')
    drift = copy.deepcopy(alias)
    drift['recommend']['candidate_k'] += 1
    with pytest.raises(ValueError, match='validation recipe differs'):
        validate_configuration(tmp_path, drift, quality, 'integration')
    ordered = copy.deepcopy(alias)
    ordered['simulator']['taxonomy'] = dict(reversed(list(ordered['simulator']['taxonomy'].items())))
    with pytest.raises(ValueError, match='recipe/order differs'):
        validate_configuration(tmp_path, ordered, quality, 'integration')


@pytest.mark.parametrize('defect', [None, 'small', 'forced', 'guard', 'cohort', 'candidate', 'traffic', 'untrained', 'natural', 'split_logs'])
def test_separated_full_ct_never_hides_retention_or_fabricates_rollback(tmp_path, defect):
    from scripts.check_submission_evidence import source, validate_separated_ct
    from src.common.artifacts import write_json
    from src.ct.retrain_trigger import settings
    config=checker.full_config()
    metric=dict(ctr_auc=.8,ctr_samples=200000,validation_fingerprint='paired')
    natural=dict(status='PARTIAL',scale='full',data_fingerprint='dataset',
        retraining=dict(status='RETAINED',comparison=dict(candidate=metric,training_reports={})),
        real_reload_and_rollback=False,observed_new_events=10000,threshold=10000,
        repeated_trigger=dict(status='WAITING'),source_hashes={},
        checks=dict(full_three_model_retraining=True,threshold=True,event_watermark=True,paired_valid=True,real_reload_and_rollback=False))
    training=dict(status='PASS',training_sources={})
    for name in ('candidate','ranking','session'):
        path=name+'.json';write_json(tmp_path/path,dict(status='PASS',scale='full',checkpoint_reload='PASS'))
        training['training_sources'][name]=source(tmp_path,path)
        natural['retraining']['comparison']['training_reports'][name]=file_hash(tmp_path/path)
    if defect=='natural':natural['retraining']['status']='PROMOTED'
    write_json(tmp_path/'natural.json',natural)
    natural_link=source(tmp_path,'natural.json')
    log=tmp_path/'lifecycle.jsonl';log.write_text('\n'.join(json.dumps(dict(event=e)) for e in ['registered','initialized','promoted','reloaded','rollback','reloaded'])+'\n')
    hashes={'ranking/deepfm.pt':'actual-trained-identity'}
    drill=dict(status='PASS',scale='full',scenario='controlled_initial_constant_ranker',natural_retraining='RETAINED',
        data_fingerprint='dataset',counts=dict(products=50000,users=10000,events=1000000),
        production_unchanged=True,real_reload_and_rollback=True,fixture_active='v1.0',natural=natural_link,
        source_hashes={},guard=settings(config),comparison=dict(split='valid',validation_fingerprint='paired',
        baseline=dict(ctr_auc=.5,validation_fingerprint='paired'),candidate=dict(metric)),
        original_candidate_hashes=dict(hashes),candidate_hashes=dict(hashes),
        http=[dict(status=200,version=v) for v in ['v1.0','v1.0','v1.1','v1.1','v1.0','v1.0']],reloads=[{},{}],
        lifecycle=dict(source='lifecycle.jsonl',sha256=file_hash(log)))
    if defect=='small':drill['counts']['products']=400
    elif defect=='forced':drill['comparison']['candidate']['ctr_auc']=.5001
    elif defect=='guard':drill['guard']['min_improvement']=0
    elif defect=='cohort':drill['comparison']['candidate']['validation_fingerprint']='different'
    elif defect=='candidate':drill['candidate_hashes']['ranking/deepfm.pt']='different'
    elif defect=='traffic':drill['http'][-1]['version']='v1.1'
    elif defect=='untrained':training['training_sources'].pop('session')
    if defect=='split_logs':
        log.write_text('\n'.join(json.dumps(dict(event=e)) for e in ['registered','initialized','promoted','rollback'])+'\n')
        drill['lifecycle']['sha256']=file_hash(log)
        (tmp_path/'reload.jsonl').write_text('\n'.join(json.dumps(dict(event='reloaded')) for _ in range(2))+'\n')
    write_json(tmp_path/'drill.json',drill);write_json(tmp_path/'training.json',training)
    write_json(tmp_path/'candidate_validation.json',dict(bundle_hashes=hashes));write_json(tmp_path/'configuration.json',config)
    receipt={key:source(tmp_path,path) for key,path in dict(natural='natural.json',controlled_lifecycle='drill.json',
        training='training.json',candidate_validation='candidate_validation.json',configuration='configuration.json').items()}
    if defect=='split_logs':
        receipt['controlled_reload']=dict(source='reload.jsonl',sha256=file_hash(tmp_path/'reload.jsonl'))
    if defect in (None, 'split_logs'):
        validate_separated_ct(tmp_path,receipt,'dataset')
        if defect=='split_logs':
            (tmp_path/'reload.jsonl').write_text('')
            with pytest.raises(ValueError):validate_separated_ct(tmp_path,receipt,'dataset')
    else:
        with pytest.raises(ValueError):validate_separated_ct(tmp_path,receipt,'dataset')
