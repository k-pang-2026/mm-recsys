import faiss
import numpy as np
import pytest
from src.search.index import SearchIndex


def test_unique_vector_buckets_expand_without_losing_products():
    index = faiss.IndexFlatIP(2); index.add(np.eye(2, dtype=np.float32))
    search = SearchIndex(index, ['P1', 'P2', 'P3'], [[0, 2], [1]])
    hits = search.search(np.array([[1, 0]], np.float32), 3)[0]
    assert [h.product_id for h in hits] == ['P1', 'P3', 'P2']
    assert [h.score for h in hits] == [1, 1, 0]
    assert search.search(np.array([[1, 0]], np.float32), 3, {'P2'})[0][0].product_id == 'P2'
    assert search.search(np.array([[1, 0]], np.float32), 3, set()) == [[]]


@pytest.mark.parametrize('members', [[[0], [0]], [[0], []], [[0.0], [1]], [[0], [3]]])
def test_invalid_bucket_mapping_is_rejected(members):
    index = faiss.IndexFlatIP(2); index.add(np.eye(2, dtype=np.float32))
    with pytest.raises(ValueError, match='membership'):
        SearchIndex(index, ['A', 'B'], members)


def test_faiss_negative_one_is_filtered_not_mapped(monkeypatch):
    index = faiss.IndexFlatIP(2); index.add(np.eye(2, dtype=np.float32))
    monkeypatch.setattr(index, 'search', lambda *a: (np.array([[1, -np.inf]], np.float32), np.array([[0, -1]])))
    search = SearchIndex(index, ['A', 'LAST'])
    assert [h.product_id for h in search.search(np.array([[1, 0]], np.float32), 2)[0]] == ['A']
