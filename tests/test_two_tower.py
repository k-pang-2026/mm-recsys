from __future__ import annotations

import copy
import json

import numpy as np
import pandas as pd
import pytest
import torch

from src.common.config import load_config
from src.common.seed import set_seed
from src.recommendation.candidate import ExactCandidate, top_indices
from src.recommendation.datasets import NegativeSampler, TrainingDataset, context_for
from src.recommendation.eval_candidate import Evaluation
from src.recommendation.features import FeatureEncoder, ITEM_FIELDS, PAD, UNK
from src.recommendation.train_two_tower import load_bundle, save_bundle, tiny_fit
from src.recommendation.two_tower import TwoTower, weighted_loss


@pytest.fixture
def fixture():
    cfg = load_config()
    cfg['recommend']['candidate'].update(history_n=5, batch_size=64, threads=1)
    torch.set_num_threads(1)
    set_seed(cfg['seed'])
    start = pd.Timestamp('2025-01-01', tz='UTC')
    cutoff = start + pd.Timedelta(days=10)
    products = pd.DataFrame({'product_id': [f'P{i:04d}' for i in range(401)],
                             'price': np.arange(401, dtype=float) + 100,
                             'created_at': [start] * 400 + [cutoff + pd.Timedelta(days=1)]})
    for j, field in enumerate(ITEM_FIELDS):
        products[field] = [f'{field}-{i % (j + 5)}' for i in range(400)] + ['future-only']
    products.loc[400, 'price'] = 1e12
    users = pd.DataFrame({'user_id': ['u1', 'u2', 'u3'], 'age_group': ['18-24', '35-44', '45+'],
                          'gender': ['F', 'M', 'F'], 'signup_at': [start] * 3, 'persona': ['hidden'] * 3})
    rows = []
    for day in range(1, 8):
        for i, uid in enumerate(['u1', 'u2']):
            rows.append((f'e{day}-{uid}', uid, f'P{i:04d}', 'purchase' if day % 2 else 'view', start + pd.Timedelta(days=day)))
    train = pd.DataFrame(rows, columns=['event_id', 'user_id', 'product_id', 'event_type', 'timestamp'])
    valid = pd.DataFrame([('v1', 'u1', 'P0000', 'cart', cutoff + pd.Timedelta(days=1)),
                          ('v2', 'u1', 'P0000', 'purchase', cutoff + pd.Timedelta(days=2)),
                          ('v3', 'u2', 'P0400', 'purchase', cutoff + pd.Timedelta(days=2))], columns=train.columns)
    data = dict(products=products, users=users, train=train, valid=valid,
                manifest={'boundaries': {'train': {'end': cutoff.isoformat()}},
                          'generation_fingerprint': 'fixture', 'file_hashes': {'products.parquet': 'fixture-catalog'}})
    encoder = FeatureEncoder.fit(products, users, cutoff)
    table = encoder.item_table(products.sample(frac=1, random_state=7))
    return cfg, data, encoder, table, cutoff


def test_train_only_vocab_price_and_public_id_mapping(fixture):
    _, data, encoder, table, _ = fixture
    assert all('future-only' not in encoder.vocabs[field] for field in ITEM_FIELDS)
    assert encoder.price_mean == pytest.approx(np.log1p(np.arange(400) + 100).mean())
    assert (table.categories[table.id_to_index['P0400']] == UNK).all()
    assert table.public_ids([table.id_to_index['P0007']]) == ['P0007']
    assert (table.categories[PAD] == PAD).all()
    assert FeatureEncoder.from_dict(encoder.to_dict()).digest == encoder.digest
    for invalid in [0, -1, len(table.ids)]:
        with pytest.raises(ValueError): table.public_ids([invalid])


def test_no_latent_persona_or_future_labels_in_features(fixture):
    cfg, data, encoder, table, cutoff = fixture
    one = TrainingDataset(data['train'], data['users'], encoder, table, cfg)
    altered_users = data['users'].copy(); altered_users['persona'] = 'other hidden tastes'
    two = TrainingDataset(data['train'], altered_users, encoder, table, cfg)
    assert torch.equal(one.profile, two.profile)
    assert torch.equal(one.history, two.history)
    assert torch.equal(one.demographics, two.demographics)
    assert torch.equal(one.items, two.items)
    assert one.diagnostics['strictly_preceding_history']
    with pytest.raises(ValueError, match='cutoff'):
        TrainingDataset(pd.concat([data['train'], data['valid']]), data['users'], encoder, table, cfg)


def test_tied_timestamp_history_and_purchase_profile(fixture):
    cfg, data, encoder, table, _ = fixture
    events = data['train'].iloc[:1].copy()
    second = events.copy(); second['event_id'] = 'same-time'; second['product_id'] = 'P0002'
    later = events.copy(); later['event_id'] = 'later'; later['timestamp'] += pd.Timedelta(seconds=1)
    dataset = TrainingDataset(pd.concat([events, second, later]), data['users'], encoder, table, cfg)
    assert (dataset.history[:2] == 0).all()
    assert (dataset.profile[:2] == 0).all()
    assert set(dataset.history[2].tolist()) == {0, table.id_to_index['P0000'], table.id_to_index['P0002']}
    assert dataset.profile[2, -1] == 1


def test_negative_policy_excludes_only_past_and_current(fixture):
    cfg, data, encoder, table, _ = fixture
    dataset = TrainingDataset(data['train'], data['users'], encoder, table, cfg)
    rows = data['train'].set_index('event_id')
    for i, event_id in enumerate(dataset.event_ids):
        row = rows.loc[event_id]
        earlier = data['train'][(data['train'].user_id == row.user_id) & (data['train'].timestamp < row.timestamp)]
        excluded = {table.id_to_index[pid] for pid in earlier.product_id} | {int(dataset.items[i, 0])}
        negatives = dataset.items[i, 1:].tolist()
        assert len(negatives) == len(set(negatives)) == 4
        assert not set(negatives) & excluded
        assert (table.created[negatives] <= row.timestamp.value).all()
    sampler = NegativeSampler(table, 42)
    future_positive = table.id_to_index['P0001']
    pool = set(table.eligible(data['train'].timestamp.min()))
    # If future positives were excluded this sole allowed negative would be impossible.
    assert set(sampler.sample(data['train'].timestamp.min(), pool - {future_positive})) == {future_positive}
    assert sampler.small_pool == 1
    with pytest.raises(ValueError, match='no observable valid negative'):
        sampler.sample(data['train'].timestamp.min(), pool)


def test_random_sample_repeatability(fixture):
    _, _, _, table, cutoff = fixture
    a, b = NegativeSampler(table, 91), NegativeSampler(table, 91)
    c = NegativeSampler(table, 92)
    excluded = {1, 2}
    assert np.array_equal(a.sample(cutoff, excluded), b.sample(cutoff, excluded))
    assert not np.array_equal(a.sample(cutoff, excluded), c.sample(cutoff, excluded))
    with pytest.raises(ValueError): NegativeSampler(table, 1, count=5)


def test_shapes_unit_norm_padding_and_both_tower_gradients(fixture):
    cfg, data, encoder, table, _ = fixture
    dataset = TrainingDataset(data['train'], data['users'], encoder, table, cfg)
    model = TwoTower(encoder, table, cfg['recommend']['candidate'])
    batch = {key: torch.stack([dataset[i][key] for i in range(6)]) for key in dataset[0]}
    logits, users, items = model(batch)
    assert logits.shape == (6, 5) and users.shape == (6, 64) and items.shape == (6, 5, 64)
    assert torch.allclose(users.norm(dim=-1), torch.ones(6), atol=1e-6)
    assert torch.allclose(items.norm(dim=-1), torch.ones(6, 5), atol=1e-6)
    assert torch.equal(model.encode_items(torch.zeros(3, dtype=torch.long)), torch.zeros(3, 64))
    user = model.encode_users(batch['history'], batch['demographics'], batch['profile'])
    padded = torch.cat([torch.zeros((6, 3), dtype=torch.long), batch['history']], dim=1)
    assert torch.allclose(user, model.encode_users(padded, batch['demographics'], batch['profile']), atol=1e-6)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.01)
    before = model.item_mlp[0].weight.detach().clone()
    weighted_loss(logits, batch['weights']).backward()
    assert model.user_mlp[0].weight.grad.abs().sum() > 0
    assert model.item_mlp[0].weight.grad.abs().sum() > 0
    assert model.item_embeddings[0].weight.grad.abs().sum() > 0
    optimizer.step()
    assert not torch.equal(before, model.item_mlp[0].weight)


def test_tiny_train_only_fit(fixture):
    cfg, data, encoder, table, _ = fixture
    dataset = TrainingDataset(data['train'], data['users'], encoder, table, cfg)
    model = TwoTower(encoder, table, cfg['recommend']['candidate'])
    result = tiny_fit(model, dataset, cfg)
    assert result['status'] == 'PASS' and result['final_accuracy'] >= 0.95
    assert set(result['event_ids']) <= set(data['train'].event_id)


def test_seeded_tower_repeatability(fixture):
    cfg, _, encoder, table, _ = fixture
    set_seed(cfg['seed'])
    first = TwoTower(encoder, table, cfg['recommend']['candidate'])
    set_seed(cfg['seed'])
    second = TwoTower(encoder, table, cfg['recommend']['candidate'])
    assert torch.equal(first.encode_items(torch.tensor([1, 2, 3])), second.encode_items(torch.tensor([1, 2, 3])))


def test_exact_300_macro_unique_truth_and_unavailable_targets(fixture):
    cfg, data, encoder, table, cutoff = fixture
    evaluation = Evaluation(data, encoder, table, cfg)
    assert evaluation.truth == {'u1': {'P0000'}, 'u2': {'P0400'}}
    assert len(evaluation.eligible) == 400
    ranked = [table.public_ids(evaluation.eligible[:300])] * 2
    result = evaluation.measure(ranked)
    assert result['recall_at_300'] == 0.5
    assert result['macro_users'] == 2 and result['empty_target_users'] == 1
    assert result['unavailable_truth_items'] == 1
    assert isinstance(result['rare_truth_items'], int) and isinstance(result['new_truth_items'], int)
    assert result['cohorts']['unavailable_target']['recall_at_300'] == 0
    assert evaluation.contexts[0].history_count == 7
    with pytest.raises(ValueError, match='count'):
        evaluation.measure([ranked[0][:299], ranked[1]])
    with pytest.raises(ValueError, match='duplicate'):
        evaluation.measure([[ranked[0][0]] * 300, ranked[1]])


def test_cutoff_is_strict_and_target_never_supplied_to_baseline(fixture):
    cfg, data, encoder, table, cutoff = fixture
    events = data['train'].copy()
    events['timestamp'] = cutoff
    context = context_for(events, data['users'].iloc[0].to_dict(), encoder, table, cutoff, 5)
    assert context.history_count == 0 and not context.observed
    evaluation = Evaluation(data, encoder, table, cfg)
    before = evaluation.baseline_metrics()
    altered = copy.deepcopy(data)
    altered['valid']['product_id'] = 'P0300'
    other = Evaluation(altered, encoder, table, cfg)
    assert np.array_equal(evaluation.baselines.popularity, other.baselines.popularity)
    assert np.array_equal(evaluation.baselines.history_scores(evaluation.contexts[0], evaluation.eligible),
                          other.baselines.history_scores(other.contexts[0], other.eligible))
    assert before['train_popularity']['candidate_count_min'] == 300


def test_cold_users_and_small_catalog_still_in_primary(fixture):
    cfg, data, encoder, table, cutoff = fixture
    altered = copy.deepcopy(data)
    altered['valid'].loc[0, 'user_id'] = 'u3'
    altered['valid'].loc[1, 'user_id'] = 'u3'
    evaluation = Evaluation(altered, encoder, table, cfg)
    result = evaluation.measure([table.public_ids(evaluation.eligible[:300])] * 2)
    assert result['macro_users'] == 2 and result['cohorts']['cold']['users'] == 1
    indices = np.array([1, 2, 3])
    assert top_indices(np.ones(3), indices).tolist() == [1, 2, 3]
    assert top_indices(np.ones(3), indices, excluded=frozenset({1})).tolist() == [2, 3]


def test_exact_dot_product_and_mapping(fixture):
    cfg, data, encoder, table, _ = fixture
    model = TwoTower(encoder, table, cfg['recommend']['candidate'])
    evaluation = Evaluation(data, encoder, table, cfg)
    candidate = ExactCandidate(model, table, evaluation.eligible, 64)
    context = evaluation.contexts[0]
    scores = np.einsum('d,id->i', candidate.user_vectors([context])[0], candidate.vectors)
    expected = table.public_ids(top_indices(scores, evaluation.eligible))
    assert candidate.retrieve(context) == expected
    assert len(set(expected)) == 300 and 'P0400' not in expected


def test_bundle_roundtrip_and_checksum_rejection(fixture, tmp_path):
    cfg, data, encoder, table, _ = fixture
    model = TwoTower(encoder, table, cfg['recommend']['candidate'])
    save_bundle(tmp_path, model, encoder, table, cfg, data, 2, 0.1)
    loaded, loaded_encoder, loaded_table, _ = load_bundle(tmp_path, data, cfg)
    assert loaded_encoder.digest == encoder.digest and loaded_table.ids == table.ids
    assert torch.equal(loaded.encode_items(torch.tensor([1, 2])), model.encode_items(torch.tensor([1, 2])))
    (tmp_path / 'item_ids.json').write_text(json.dumps(['wrong']))
    with pytest.raises(ValueError, match='checksum'):
        load_bundle(tmp_path, data, cfg)
