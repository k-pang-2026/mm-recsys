from __future__ import annotations

import copy
import json
from pathlib import Path

import pandas as pd
import pytest

from src.common.artifacts import file_hash, write_json
from src.common.config import load_config
from src.evaluation.recommendation import aggregate
from src.evaluation.reporting import metric, relative_lift
from src.evaluation.run_all import ab_evidence, check_frozen, metric_rows


def test_coverage_uses_all_fixed_users_while_quality_keeps_unavailable_truth():
    rows = [('u1', ['p1']), ('u2', ['p2']), ('no-truth', ['p3'])]
    truth = dict(u1={'p1'}, u2={'future-unavailable'})
    value = aggregate(rows, truth, 10)
    assert value['hit_rate_at_50'] == .5
    assert value['ndcg_at_50'] == .5
    assert value['truth_users'] == 2 and value['coverage_users'] == 3
    assert value['coverage'] == .3
    assert aggregate([('u', [])], {}, 10)['hit_rate_at_50'] is None
    with pytest.raises(ValueError, match='unique user'):
        aggregate([('u', ['p']), ('u', ['p2'])], truth, 10)
    with pytest.raises(ValueError, match='duplicate recommendations'):
        aggregate([('u', ['p', 'p'])], truth, 10)


def test_status_never_invents_zero_or_relaxes_target():
    cfg = load_config()
    assert metric('mrr', .54999, cfg, 'valid', 'fixture')['status'] == 'FAIL'
    assert metric('mrr', .55, cfg, 'valid', 'fixture')['status'] == 'PASS'
    assert metric('search_p95_ms', 200.01, cfg, 'benchmark', 'fixture')['status'] == 'FAIL'
    for value in (None, float('nan'), float('inf'), True):
        row = metric('mrr', value, cfg, 'valid', 'fixture')
        assert row['value'] is None and row['status'] == 'UNMEASURED'
    assert relative_lift(.2, 0.) is None
    assert relative_lift(None, .2) is None
    assert relative_lift(.1, .2) == -.5


def test_search_latency_uses_worst_mode_not_average_and_missing_stays_unmeasured():
    cfg = load_config()
    api = dict(modes={mode: dict(http=dict(p95_ms=v)) for mode, v in [('text', 100.), ('image', 150.), ('hybrid', 250.)]})
    rows = metric_rows(cfg, 'valid', {}, {}, api, {}, {})
    search = next(row for row in rows if row['name'] == 'search_p95_ms')
    assert search['value'] == 250. and search['status'] == 'FAIL'
    del api['modes']['image']
    assert next(row for row in metric_rows(cfg, 'valid', {}, {}, api, {}, {}) if row['name'] == 'search_p95_ms')['value'] is None


def test_test_recipe_rejects_changed_data_models_code_and_valid_evidence(tmp_path):
    source = tmp_path / 'valid.json'
    source.write_text('{"scope":"fixture only"}')
    current = dict(config_fingerprint='cfg', models={'bundle': 'hash'}, source_hashes={'code': 'hash'}, data_manifest_sha256='data')
    selection = dict(selected_on='valid', identity=current, source='valid.json', sha256=file_hash(source))
    check_frozen(selection, current, tmp_path)
    for field in current:
        changed = copy.deepcopy(current)
        changed[field] = 'changed'
        with pytest.raises(ValueError, match='valid-frozen'):
            check_frozen(selection, changed, tmp_path)
    source.write_text('modified after freeze')
    with pytest.raises(ValueError, match='changed after'):
        check_frozen(selection, current, tmp_path)


def test_b7_reuse_requires_same_dataset_models_and_experiment_scope(tmp_path):
    cfg = load_config()
    cfg['paths']['results_dir'] = str(tmp_path)
    models = {kind: dict(hashes={f'{kind}.pt': kind}) for kind in ('candidate', 'ranking', 'session')}
    assert ab_evidence(cfg, {}, {})['status'] == 'UNMEASURED'
    report = dict(identity=dict(data_fingerprint='data', bundle_metadata=models, source_hashes={}),
        seed=cfg['seed'], strategies={name: cfg['serving']['ab_test'][name] for name in ('control', 'treatment')},
        outcome_model=dict(parameters=cfg['serving']['ab_test']['outcome']),
        days=cfg['serving']['ab_test']['days'], top_n=cfg['serving']['ab_test']['top_n'],
        arms={}, denominators={}, inference={}, limitations=[])
    write_json(tmp_path / 'ab_test.json', report)
    assert ab_evidence(cfg, dict(generation_fingerprint='data'), models)['status'] == 'MEASURED'
    with pytest.raises(ValueError, match='experiment scope'):
        ab_evidence(cfg, dict(generation_fingerprint='other'), models)
    changed = copy.deepcopy(models)
    changed['candidate']['hashes']['candidate.pt'] = 'different'
    with pytest.raises(ValueError, match='different recommendation models'):
        ab_evidence(cfg, dict(generation_fingerprint='data'), changed)


def test_recommendation_evaluator_uses_real_loader_and_fixed_origin(tmp_path, monkeypatch):
    from src.recommendation.testing import service_fixture
    import src.evaluation.recommendation as evaluator
    cfg, data = service_fixture(tmp_path)
    data['valid']['event_type'] = 'cart'
    labels = pd.DataFrame([dict(user_id='u', product_id='p00', exposed_at=data['valid'].timestamp.iloc[0],
                               ctr=1, cvr=0, ctr_mask=1, cvr_mask=1)])
    monkeypatch.setattr(evaluator, 'prepare', lambda *_: (data, {'valid': labels}, {'valid': {'fixture': True}}))
    value = evaluator.evaluate(cfg, 'valid')
    assert value['cohort']['total_users'] == value['cohort']['truth_users'] == 1
    assert set(value['metrics']) == {'train_popularity', 'two_tower', 'deepfm', 'full_pipeline'}
    assert all(row['coverage_users'] == 1 and row['catalog_items'] == 30 for row in value['metrics'].values())
    assert value['candidate']['ann_two_tower']['candidate_count_min'] == 30
    assert value['classification']['cvr']['auc'] is None
    assert value['cutoff'] == data['manifest']['boundaries']['train']['end']
