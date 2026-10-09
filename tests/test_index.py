import json
import faiss
import numpy as np
import pytest

from src.common.config import load_config
from src.search.encoder import unit_vectors
from src.search.index import make_index, SearchIndex
from src.search.eval_support import ann_agreement, exact_search
from src.search.build_index import fuse


def test_hnsw_explicit_ip_save_load_and_sentinel_filter(tmp_path):
    vectors = unit_vectors(np.random.default_rng(42).normal(size=(80, 16)))
    spec = load_config()['search']['faiss']
    index = make_index(vectors, spec, 42)
    ids = [f'product-{i*11}' for i in range(len(vectors))]
    original = SearchIndex(index, ids).search(vectors[:5], 100)
    assert len(original[0]) == len(ids)  # -1 padded labels never map to the last product.
    assert original[0][0].product_id == ids[0]
    assert index.metric_type == faiss.METRIC_INNER_PRODUCT and index.hnsw.efSearch >= 100
    path = tmp_path/'index.faiss'; faiss.write_index(index, str(path))
    loaded = SearchIndex(faiss.read_index(str(path)), ids).search(vectors[:5], 100)
    assert loaded == original
    scores, labels = index.search(vectors[:5], 10)
    agreement = ann_agreement(vectors, vectors[:5], scores, labels, 10)
    assert agreement['label_overlap_recall'] == 1
    assert agreement['max_reported_score_error'] < 1e-5


def test_duplicate_vectors_use_equivalent_exact_scores():
    vectors = np.tile(np.array([[1, 0]], np.float32), (30, 1))
    scores = np.ones((1, 5), np.float32)
    labels = np.array([[20, 21, 22, 23, 24]])
    result = ann_agreement(vectors, vectors[:1], scores, labels, 5)
    assert result['label_overlap_recall'] == 0
    assert result['exact_score_tie_aware_agreement'] == 1


@pytest.mark.parametrize('mutation,match', [
    ({'type': 'IVFPQ', 'nlist': 256}, '9984'),
    ({'type': 'IVFPQ', 'nlist': 1, 'm': 3}, 'dimensions'),
    ({'metric': 'l2'}, 'inner_product'),
    ({'type': 'Flat'}, 'no silent fallback'),
    ({'threads': 100}, 'threads'),
])
def test_invalid_faiss_config_never_falls_back(mutation, match):
    vectors = unit_vectors(np.random.default_rng(1).normal(size=(100, 16)))
    spec = load_config()['search']['faiss']; spec.update(mutation)
    with pytest.raises(ValueError, match=match):
        make_index(vectors, spec, 42)


def test_ivfpq_valid_training_uses_ip_and_preserves_count():
    vectors = unit_vectors(np.random.default_rng(1).normal(size=(180, 8)))
    spec = {'type': 'IVFPQ', 'metric': 'inner_product', 'threads': 1,
            'nlist': 2, 'm': 2, 'nbits': 2, 'nprobe': 2}
    index = make_index(vectors, spec, 42)
    assert index.is_trained and index.ntotal == 180 and index.metric_type == faiss.METRIC_INNER_PRODUCT


def test_invalid_queries_ids_and_fusion_are_rejected():
    index = faiss.IndexFlatIP(2); index.add(np.eye(2, dtype=np.float32))
    with pytest.raises(ValueError):
        SearchIndex(index, ['same', 'same'])
    search = SearchIndex(index, ['X9', 'Z3'])
    for k in (0, True, 1.5):
        with pytest.raises(ValueError):
            search.search(np.eye(2, dtype=np.float32), k)
    with pytest.raises(ValueError, match='normalized'):
        search.search(np.ones((1, 2), np.float32), 1)
    with pytest.raises(ValueError, match='weights'):
        fuse(np.eye(2), np.eye(2), {'text_weight': 0, 'image_weight': 0})
