"""Reusing immutable user metadata must preserve exact serving features."""
from __future__ import annotations

import numpy as np
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
