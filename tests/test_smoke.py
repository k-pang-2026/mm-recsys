from src.evaluation.metrics import hit_rate_at_k, mrr


def test_hit_rate() -> None:
    assert hit_rate_at_k(["a", "b"], {"b"}, 2) == 1.0


def test_mrr_single_and_set_truth() -> None:
    assert mrr([["a", "b"]], ["b"]) == 0.5
    assert mrr([["a", "b", "c"]], [{"c", "b"}]) == 0.5
