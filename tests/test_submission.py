"""Submission checks must reject altered evidence and retain incomplete scope."""
from __future__ import annotations

import json
from pathlib import Path
import shutil

import httpx
import pytest

from scripts import check_submission as checker
from scripts.check_submission_evidence import (QUALITY, SMOKE, assemble_acceptance, audit_python,
                                               check_hashes, collect_quality, read_json)

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
    for name in names:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
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
