"""Reusing immutable user metadata must preserve exact serving features."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.recommendation.testing import service_fixture
from src.recommendation.feature_store import RecommendationFeatureStore
from src.recommendation.service import create_service


@pytest.mark.parametrize('uid,recent,count', [('u', [], 0), ('unknown', [], 0),
                                             ('u', ['p00', 'p01', 'missing'], 3)])
def test_resident_lookup_matches_original_dataframe_path(tmp_path, uid, recent, count):
    cfg, data = service_fixture(tmp_path)
    service = create_service(cfg, RecommendationFeatureStore(cfg, data['products']))
    products = service.table.ids[1:]
    args = (uid, products, service.at, data['users'], service.table,
            service.history_index, recent, count)
    original = service.ranking_encoder.serving(*args)
    resident = service.ranking_encoder.serving(*args, user_rows=service.user_rows)
    assert all(np.array_equal(a, b) for a, b in zip(original, resident))


@pytest.mark.parametrize('cross_features', [False, True])
@pytest.mark.parametrize('uid,recent,count', [('u', [], 0), ('unknown', [], 0),
                                             ('u', ['p00', 'p01', 'missing'], 3)])
def test_array_serving_matches_legacy_normalized_dataframe_features(tmp_path, cross_features, uid, recent, count):
    cfg, data = service_fixture(tmp_path)
    service = create_service(cfg, RecommendationFeatureStore(cfg, data['products']))
    encoder, table = service.ranking_encoder, service.table
    encoder.cross_features = cross_features
    rng = np.random.default_rng(42)
    encoder.mean = rng.normal(size=len(encoder.mean)).astype(np.float32)
    encoder.std = rng.uniform(.1, 3, size=len(encoder.std)).astype(np.float32)
    products = table.ids[1:]
    labels = pd.DataFrame(dict(user_id=[uid]*len(products), product_id=products,
                               exposed_at=[service.at]*len(products)))
    sparse, dense = encoder.transform(labels, data['users'], table, service.history_index)
    raw = dense * encoder.std + encoder.mean
    known = [table.id_to_index[p] for p in recent if p in table.id_to_index and table.created[table.id_to_index[p]] <= service.at.value]
    if known:
        rows = np.array([table.id_to_index[p] for p in products]); cats = table.categories
        for field, target in [(0, 3), (2, 4), (3, 5)]:
            counts = np.bincount(cats[known, field], minlength=int(cats[:, field].max())+1) / len(known)
            raw[:, target] = counts[cats[rows, field]]
        raw[:, 8] = np.abs(table.prices[rows, 0] - table.prices[known, 0].mean())
        raw[:, 9] = 1
    raw[:, 10] = np.log1p(count)
    expected = (raw - encoder.mean) / encoder.std
    if not cross_features:
        expected[:, 3:10] = 0
    actual_sparse, actual_dense = encoder.serving(uid, products, service.at, data['users'], table,
                                                 service.history_index, recent, count, service.user_rows)
    np.testing.assert_array_equal(actual_sparse, sparse)
    np.testing.assert_allclose(actual_dense, expected, rtol=1e-6, atol=2e-6)
    with pytest.raises(ValueError, match='before product registration'):
        encoder.serving(uid, products, data['products'].created_at.min() - pd.Timedelta(days=1),
                        data['users'], table, service.history_index, [], 0)
