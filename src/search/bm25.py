"""BM25 uses the same observable text aliases; no image-only baseline is invented."""
from __future__ import annotations

import numpy as np
from rank_bm25 import BM25Okapi
from src.search.index import SearchHit
from src.search.text import tokenize


class BM25Search:
    def __init__(self, ids: list[str], texts: list[str]):
        if not ids or len(ids) != len(texts) or len(set(ids)) != len(ids):
            raise ValueError('aligned unique BM25 IDs and texts required')
        self.ids = ids
        tokens = [tokenize(text) for text in texts]
        if any(not values for values in tokens):
            raise ValueError('BM25 documents must contain tokens')
        self.model = BM25Okapi(tokens)

    def search(self, query: str, k: int, eligible_ids: set[str] | None = None) -> list[SearchHit]:
        if isinstance(k, bool) or not isinstance(k, int) or k < 1:
            raise ValueError('k must be positive')
        scores = self.model.get_scores(tokenize(query))
        eligible = np.array([i for i, id_ in enumerate(self.ids) if eligible_ids is None or id_ in eligible_ids], dtype=int)
        # Stable ID-aligned tie handling, without substituting relevance into retrieval.
        selected = eligible[np.argsort(-scores[eligible], kind='stable')[:k]]
        return [SearchHit(self.ids[i], float(scores[i])) for i in selected]
