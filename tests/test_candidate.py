"""Persisted ANN contract, exact agreement, exclusions and cutoff/refill regressions."""
from __future__ import annotations

import copy
import json

import faiss
import numpy as np
import pytest

from tests.test_two_tower import fixture
from src.recommendation.candidate import FaissCandidate
from src.recommendation.eval_candidate import Evaluation
from src.recommendation.index import build_index, load_index
from src.recommendation.train_two_tower import load_bundle, save_bundle
from src.recommendation.two_tower import TwoTower


def setup_index(fixture, tmp_path):
    cfg, data, encoder, table, _ = fixture
    model = TwoTower(encoder, table, cfg['recommend']['candidate'])
    meta = save_bundle(tmp_path, model, encoder, table, cfg, data, 1, 0.1)
    build_index(tmp_path, model, table, cfg, meta)
    model, _, _, meta = load_bundle(tmp_path, data, cfg)
    index, manifest = load_index(tmp_path, table, meta)
    return cfg, data, encoder, table, model, index, meta, manifest


def test_ann_roundtrip_cutoff_and_exact_agreement(fixture, tmp_path):
    cfg, data, encoder, table, model, index, _, manifest = setup_index(fixture, tmp_path)
    evaluation = Evaluation(data, encoder, table, cfg)
    result = evaluation.ann_metrics(model, index)
    assert manifest['ntotal'] == 401
    assert result['ann_agreement_at_300'] > 0.99
    assert result['ann_two_tower']['candidate_count_min'] == 300
    assert result['ann_two_tower']['unavailable_truth_items'] == 1
    candidate = FaissCandidate(model, table, evaluation.eligible, index)
    ranked = candidate.retrieve(evaluation.contexts[0])
    assert len(ranked) == len(set(ranked)) == 300 and 'P0400' not in ranked


def test_adaptive_refill_after_cutoff_and_purchase_exclusions(fixture, tmp_path):
    cfg, data, encoder, table, model, index, _, _ = setup_index(fixture, tmp_path)
    evaluation = Evaluation(data, encoder, table, cfg)
    eligible = evaluation.eligible[:350]
    candidate = FaissCandidate(model, table, eligible, index)
    context = copy.deepcopy(evaluation.contexts[0])
    context.purchased = frozenset(eligible[:40])
    ranked = candidate.retrieve(context, exclude_purchased=True)
    assert len(ranked) == len(set(ranked)) == 300
    assert not set(ranked) & set(table.public_ids(list(context.purchased)))
    candidate = FaissCandidate(model, table, eligible[:5], index)
    assert len(candidate.retrieve(context)) == 5
    assert candidate.retrieve(context, exclude_purchased=True) == []


def test_refill_ignores_negative_labels_and_deduplicates(fixture):
    cfg, data, encoder, table, _ = fixture
    model = TwoTower(encoder, table, cfg['recommend']['candidate'])
    class FakeIndex:
        ntotal = 401
        def __init__(self): self.fetches = []
        def search(self, vector, k):
            self.fetches.append(k)
            # First search has no eligible rows, forcing refill to the full catalog.
            labels = np.full((1, k), -1, dtype=np.int64)
            if k == self.ntotal:
                labels[0, :4] = [0, 0, 1, 2]
            return np.ones((1, k), np.float32), labels
    index = FakeIndex()
    candidate = FaissCandidate(model, table, np.array([1, 2, 3]), index)
    context = Evaluation(data, encoder, table, cfg).contexts[0]
    assert candidate.retrieve(context, k=3) == table.public_ids([1, 2, 3])
    assert index.fetches[0] == 6 and index.fetches[-1] == 401


def test_index_tampering_and_stale_manifest_rejected(fixture, tmp_path):
    _, data, _, table, _, _, meta, _ = setup_index(fixture, tmp_path)
    altered = copy.deepcopy(meta); altered['catalog_sha256'] = 'stale'
    with pytest.raises(ValueError, match='stale index'): load_index(tmp_path, table, altered)
    index_path = tmp_path / 'item_index.faiss'
    original = index_path.read_bytes()
    index_path.write_bytes(original + b'changed')
    with pytest.raises(ValueError, match='checksum'): load_index(tmp_path, table, meta)
    index_path.write_bytes(original)
    manifest = json.loads((tmp_path / 'index_manifest.json').read_text())
    manifest['ef_search'] = 1
    (tmp_path / 'index_manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='manifest checksum'): load_index(tmp_path, table, meta)


def test_candidate_acceptance_refuses_dev_valid_and_stale_measurements():
    from src.recommendation.bench_candidate import metrics
    score = {'recall_at_300': 0.5, 'candidate_count_min': 300}
    training = {'scale': 'full', 'status': 'PASS', 'seed': 42, 'best_epoch': 2,
                'checkpoint_reload': 'PASS', 'best_valid_exact': score, 'tiny_train_fit': {'status': 'PASS'},
                'sampling': {'strictly_preceding_history': True, 'random_negatives_per_positive': 4},
                'contract': {'data_fingerprint': 'data'},
                'bundle': {'hashes': {'two_tower.pt': 'model'}, 'config_fingerprint': 'cfg'}}
    evaluation = {'scale': 'full', 'status': 'PASS', 'model_sha256': 'model', 'bundle_meta': {'config_fingerprint': 'cfg'},
                  'data_counts': {'products': 50000, 'users': 10000, 'events': 1000000},
                  'exact_flat_ip': score, 'ann_two_tower': score,
                  'baselines': {'train_popularity': {'recall_at_300': 0.1}}, 'ann_agreement_at_300': 0.99,
                  'contract': {'split': 'test', 'data_fingerprint': 'data', 'cutoff': 'cutoff'},
                  'index_manifest': {'index_sha256': 'index'}, 'environment': {}}
    bench = {'scale': 'full', 'context_split': 'test', 'model_sha256': 'model', 'data_fingerprint': 'data',
             'config_fingerprint': 'cfg', 'index_sha256': 'index', 'cutoff': 'cutoff', 'warmup': 10, 'calls': 100,
             'candidate_count_min': 300, 'p95_ms': 10}
    assert metrics(evaluation, training, bench)['status'] == 'PASS'
    for path, replacement in [('scale', 'dev'), ('contract', dict(evaluation['contract'], split='valid')),
                              ('ann_two_tower', dict(score, recall_at_300=0.29)),
                              ('ann_two_tower', dict(score, candidate_count_min=299))]:
        altered = copy.deepcopy(evaluation); altered[path] = replacement
        assert metrics(altered, training, bench)['status'] == 'FAIL'
    for path, replacement in [('p95_ms', 101), ('model_sha256', 'stale'), ('index_sha256', 'stale'),
                              ('config_fingerprint', 'stale'), ('cutoff', 'stale'), ('calls', 99)]:
        altered = dict(bench); altered[path] = replacement
        assert metrics(evaluation, training, altered)['status'] == 'FAIL'


def test_diagnosis_never_selects_on_test():
    from src.recommendation.diagnose_candidate import diagnose_ann
    with pytest.raises(ValueError, match='valid, not frozen test'):
        diagnose_ann({}, {'contract': {'split': 'test'}})


def test_hnsw_reads_exact_flat_storage_without_parallel_reconstruction(fixture, tmp_path, monkeypatch):
    from src.recommendation.index import stored_vectors
    _, _, _, table, _, index, _, _ = setup_index(fixture, tmp_path)
    def forbidden(*args):
        raise AssertionError('generic HNSW reconstruct_n must not be used')
    monkeypatch.setattr(index, 'reconstruct_n', forbidden)
    vectors = stored_vectors(index)
    assert vectors.shape == (len(table.ids) - 1, index.d)
    assert np.isfinite(vectors).all()
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-5)


def test_native_runtime_policy_is_limited_to_macos_arm(monkeypatch):
    from src.recommendation import runtime
    monkeypatch.setattr(runtime.platform, 'system', lambda: 'Darwin')
    monkeypatch.setattr(runtime.platform, 'machine', lambda: 'arm64')
    assert runtime.inference_threads({'threads': 4}) == 1
    monkeypatch.setattr(runtime.platform, 'system', lambda: 'Linux')
    assert runtime.inference_threads({'threads': 4}) == 4
    monkeypatch.setattr(runtime.platform, 'system', lambda: 'Darwin')
    monkeypatch.setattr(runtime.platform, 'machine', lambda: 'x86_64')
    assert runtime.inference_threads({'threads': 4}) == 4
