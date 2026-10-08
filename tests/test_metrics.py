import pytest
from src.evaluation.metrics import mrr, ndcg_at_k, recall_at_k


def test_recall_uses_unique_truth_and_full_denominator():
    assert recall_at_k(["a", "a", "x"], {"a", "b", "c", "d"}, 3) == 0.25
    assert recall_at_k(["a", "b", "c"], {"b", "c"}, 1) == 0.0
    assert recall_at_k(["a"], set(), 300) == 0.0


def test_ndcg_does_not_double_count_duplicates():
    assert ndcg_at_k(["a", "b"], {"a", "b"}, 2) == 1.0
    with pytest.raises(ValueError):
        ndcg_at_k(["a", "a"], {"a"}, 2)


def test_mrr_requires_matching_query_count():
    with pytest.raises(ValueError):
        mrr([["a"], ["b"]], ["a"])
