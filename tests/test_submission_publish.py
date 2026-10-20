"""Publication preserves frozen measurements and rejects stale/foreign evidence."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import publish_integration_dashboard as publisher
from src.common.artifacts import file_hash, write_json
from scripts.check_submission_evidence import source
from src.ct.model_registry import ModelRegistry, REQUIRED


@pytest.fixture
def publication(tmp_path, monkeypatch):
    cfg = dict(scale='full', paths=dict(data_dir=str(tmp_path / 'data'), model_dir=str(tmp_path),
                                      results_dir=str(tmp_path / 'results')), targets={'auc': .7})
    for name in REQUIRED:
        path = tmp_path / 'v1.0' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'frozen bundle')
    registry = ModelRegistry(tmp_path, tmp_path / 'lifecycle.jsonl')
    registry.register('v1.0', cfg, tmp_path / 'data', {}, None, 0)
    registry.initialize('v1.0')
    write_json(tmp_path / 'data/split_manifest.json', dict(scale='full', generation_fingerprint='dataset',
        counts=dict(products=50000, users=10000, events=1000000)))
    (tmp_path / 'weights.bin').write_bytes(b'frozen model')
    write_json(tmp_path / 'model.json', dict(version='frozen', hashes={'weights.bin': file_hash(tmp_path / 'weights.bin')}))
    models = {kind: dict(hashes={}) for kind in ('candidate', 'ranking', 'session')}
    quality = dict(data_fingerprint='dataset', acceptance='UNMEASURED', metrics=[dict(name='auc', value=.9)],
        identity=dict(data_manifest_sha256=file_hash(tmp_path / 'data/split_manifest.json'),
                      models={'model.json': file_hash(tmp_path / 'model.json')}),
        recommendation=dict(models=models))
    write_json(tmp_path / 'evidence/quality_full_test.json', quality)
    experiment = dict(identity=dict(data_fingerprint='dataset', bundle_metadata=models), days=30, run_id='run',
        arms={arm: dict(users=5000, cvr=.01, arm_statistics={}) for arm in ('control', 'treatment')},
        inference={}, limitations=['synthetic'])
    write_json(tmp_path / 'ab.json', experiment)
    write_json(tmp_path / 'ab_verification.json', source(tmp_path, 'ab.json'))
    write_json(tmp_path / 'ct.json', dict(scope='natural RETAINED; separate functional rollback',
        retraining=dict(status='RETAINED'), observed_new_events=10000))
    entry = source(tmp_path, 'ct.json', status='PASS', exit_code=0)
    checks = {key: dict(entry) for key in ('docker_reproduction', 'api_schemas', 'session_response', 'ct_retrain_and_rollback', 'submission')}
    checks['ab_statistics'] = source(tmp_path, 'ab_verification.json', status='PASS', exit_code=0)
    acceptance = dict(status='PASS', scale='full', data_fingerprint='dataset', checks=checks, limitations=[],
        metrics={name: source(tmp_path, 'evidence/quality_full_test.json', value=value, split='test', status='PASS')
                 for name, value in [('auc', .9), ('candidate_count', 300)]})
    write_json(tmp_path / 'docs/results/final_acceptance.json', acceptance)
    write_json(tmp_path / 'submission.json', dict(input_hashes={}, commands={}, evidence_dir='evidence', integration_checks='checks.json'))
    monkeypatch.setattr(publisher, 'load_config', lambda: cfg)
    # The aggregator's population/training/recipe contracts are tested in test_submission.py.
    monkeypatch.setattr(publisher, 'assemble_integration', lambda *args: copy.deepcopy(acceptance))
    return tmp_path


@pytest.mark.parametrize('defect', [None, 'changed_source', 'changed_model', 'changed_weights', 'changed_index', 'active_release', 'wrong_ab_dataset', 'wrong_ab_model', 'unmeasured', 'escape', 'overwrite_quality'])
def test_publish_validates_before_writing_and_preserves_quality(publication, defect):
    root = publication
    frozen = (root / 'evidence/quality_full_test.json').read_bytes()
    output = root / 'runtime/evaluation_full_test.json'
    if defect == 'changed_source':
        write_json(root / 'ct.json', dict(scope='changed after verification'))
    elif defect == 'changed_model':
        write_json(root / 'model.json', dict(version='other'))
    elif defect == 'changed_weights':
        (root / 'weights.bin').write_bytes(b'changed model')
    elif defect == 'changed_index':
        (root / 'v1.0/item_index.faiss').write_bytes(b'changed index')
    elif defect == 'active_release':
        write_json(root / 'registry.json', dict(active='v1.1'))
    elif defect in ('wrong_ab_dataset', 'wrong_ab_model'):
        ab = json.loads((root / 'ab.json').read_text())
        if defect == 'wrong_ab_dataset':
            ab['identity']['data_fingerprint'] = 'other'
        else:
            ab['identity']['bundle_metadata']['ranking']['hashes'] = {'weights': 'other'}
        write_json(root / 'ab.json', ab)
    elif defect == 'unmeasured':
        saved = json.loads((root / 'docs/results/final_acceptance.json').read_text())
        saved['status'] = 'UNMEASURED'
        write_json(root / 'docs/results/final_acceptance.json', saved)
    elif defect == 'escape':
        output = root.parent / 'outside.json'
    elif defect == 'overwrite_quality':
        output = root / 'evidence/quality_full_test.json'
    if defect:
        with pytest.raises(ValueError):
            publisher.publish(root, 'submission.json', output)
        if defect != 'overwrite_quality':
            assert not output.exists()
    else:
        report = publisher.publish(root, 'submission.json', output)
        assert report['acceptance'] == 'PASS' and report['ab']['status'] == 'MEASURED'
        assert report['metrics'] == json.loads(frozen)['metrics']
        assert report['integration']['checks']['ct_retrain_and_rollback']['sha256']
        assert report['integration']['ct']['retraining'] == 'RETAINED'
    assert (root / 'evidence/quality_full_test.json').read_bytes() == frozen
