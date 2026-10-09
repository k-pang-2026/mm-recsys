"""Aggregation must reject stale or fabricated measurement summaries."""
import copy
import pytest
from src.common.artifacts import fingerprint, write_json
from src.common.config import load_config
from src.search.finalize import finalize


@pytest.fixture
def measured_fixture(monkeypatch, tmp_path):
    import src.search.finalize as module
    cfg = load_config(); cfg['scale'] = 'full'; monkeypatch.chdir(tmp_path)
    modes = ('text', 'image', 'hybrid'); measured = {'queries': 200, 'mrr': 0.9, 'ndcg_at_10': 0.8}
    quality = {'scale': 'full', 'config_fingerprint': fingerprint(cfg), 'data_fingerprint': 'fixture-data',
        'model_fingerprint': 'fixture-model', 'query_manifest_sha256': 'fixture-query', 'split': 'test',
        'test_scores_used_for_selection': False, 'evaluation_fingerprint': 'fixture-eval',
        'per_mode': {mode: copy.deepcopy(measured) for mode in modes},
        'primary': {'queries': 600, 'mrr': 0.9, 'ndcg_at_10': 0.8}, 'eligible_catalog': 48000,
        'bm25': {mode: copy.deepcopy(measured) for mode in modes}}
    latency = {'scale': 'full', 'config_fingerprint': fingerprint(cfg), 'data_fingerprint': 'fixture-data',
        'model_fingerprint': 'fixture-model', 'query_manifest_sha256': 'fixture-query', 'concurrency': 1,
        'status': 'MEASURED', 'smoke': [{'mode': mode, 'status_code': 200} for mode in (*modes, 'multipart_hybrid')]
            + [{'invalid_payload': {}, 'status_code': 422}]*4,
        'per_mode': {mode: {'requests': 100, 'warmup': 10, 'http_samples_ms': [20.0]*100,
                          'http': {'p50_ms': 20.0, 'p95_ms': 20.0, 'p99_ms': 20.0}} for mode in modes}}
    monkeypatch.setattr(module, 'current_bundle', lambda cfg: {'manifest': {'fingerprint': 'fixture-model',
        'count': 50000, 'identity': {'data_fingerprint': 'fixture-data'}}})
    def save():
        write_json(tmp_path/'docs/results/search_test_full.json', quality)
        write_json(tmp_path/'docs/results/search_latency_full.json', latency)
        write_json(tmp_path/'docs/results/search_valid_full.json', {'fixture': True})
    save()
    return cfg, quality, latency, save


def test_aggregate_pass_preserves_global_unmeasured(measured_fixture):
    cfg, quality, latency, save = measured_fixture
    result = finalize(cfg)
    assert result['status'] == 'PASS' and result['global_system_acceptance'] == 'UNMEASURED'
    assert result['metrics']['search_p95_ms'] == 20


@pytest.mark.parametrize('mutation,match', [
    ('p95', 'observed HTTP samples'), ('cohort', 'cohort size'), ('nan', 'quality value'),
    ('mode', 'three fixed query modes'), ('model', 'different model/data'),
])
def test_inconsistent_summaries_cannot_be_declared_pass(measured_fixture, mutation, match):
    cfg, quality, latency, save = measured_fixture
    if mutation == 'p95': latency['per_mode']['hybrid']['http']['p95_ms'] = 1
    if mutation == 'cohort': quality['per_mode']['image']['queries'] = 20
    if mutation == 'nan': quality['per_mode']['text']['mrr'] = float('nan')
    if mutation == 'mode': quality['per_mode'].pop('image')
    if mutation == 'model': latency['model_fingerprint'] = 'other-model'
    save()
    with pytest.raises(ValueError, match=match):
        finalize(cfg)
