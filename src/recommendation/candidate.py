"""Exact reference and HNSW retrieval with cutoff/exclusion filtering and refill."""
from __future__ import annotations

import numpy as np
import torch

from src.recommendation.datasets import UserContext
from src.recommendation.features import ItemTable
from src.recommendation.two_tower import TwoTower


def dot_scores(users: np.ndarray, items: np.ndarray) -> np.ndarray:
    # Use the same CPU float32 backend as training for exact dot products.
    return (torch.from_numpy(users) @ torch.from_numpy(items).T).numpy()


def top_indices(scores: np.ndarray, eligible: np.ndarray, k: int = 300,
                excluded: frozenset[int] = frozenset()) -> np.ndarray:
    if scores.shape != eligible.shape or k <= 0 or not np.isfinite(scores).all():
        raise ValueError('invalid candidate scores/k')
    allowed = ~np.isin(eligible, list(excluded))
    candidates, values = eligible[allowed], scores[allowed]
    # Product rows are sorted by public ID; stable tie breaks do not depend on dataframe order.
    order = np.lexsort((candidates, -values))
    return candidates[order[:min(k, len(order))]]


class ExactCandidate:
    def __init__(self, model: TwoTower, table: ItemTable, eligible: np.ndarray, batch_size: int):
        self.model, self.table, self.eligible = model.eval(), table, eligible
        if len(eligible) != len(set(eligible)) or (eligible <= 0).any():
            raise ValueError('invalid eligible item mapping')
        vectors = []
        with torch.inference_mode():
            for start in range(0, len(eligible), batch_size):
                vectors.append(model.encode_items(torch.as_tensor(eligible[start:start + batch_size])).cpu().numpy())
        self.vectors = np.concatenate(vectors) if vectors else np.empty((0, model.item_mlp[-1].out_features), np.float32)

    def user_vectors(self, contexts: list[UserContext]) -> np.ndarray:
        with torch.inference_mode():
            return self.model.encode_users(torch.from_numpy(np.stack([c.history for c in contexts])),
                                           torch.from_numpy(np.stack([c.demographics for c in contexts])),
                                           torch.from_numpy(np.stack([c.profile for c in contexts]))).cpu().numpy()

    def retrieve(self, context: UserContext, k: int = 300, exclude_purchased: bool = False) -> list[str]:
        scores = dot_scores(self.user_vectors([context]), self.vectors)[0]
        indices = top_indices(scores, self.eligible, k, context.purchased if exclude_purchased else frozenset())
        return self.table.public_ids(indices)


class FaissCandidate:
    def __init__(self, model, table, eligible, index):
        self.model, self.table, self.eligible, self.index = model.eval(), table, eligible, index
        if len(eligible) != len(set(eligible)) or (eligible <= 0).any():
            raise ValueError('invalid eligible item mapping')
        self.allowed = set(map(int, eligible))

    user_vectors = ExactCandidate.user_vectors

    def search(self, vectors: np.ndarray, k: int = 300, excluded=frozenset()) -> list[list[str]]:
        if k <= 0 or not np.isfinite(vectors).all():
            raise ValueError('invalid candidate vectors/k')
        allowed = self.allowed - set(excluded)
        wanted = min(k, len(allowed))
        if not wanted:
            return [[] for _ in vectors]
        count = min(self.index.ntotal, max(k * 2, wanted + len(excluded)))
        ranked = []
        for vector in vectors:
            fetch = count
            while True:
                distances, labels = self.index.search(np.ascontiguousarray(vector[None], dtype=np.float32), fetch)
                valid = [(float(score), int(label) + 1) for score, label in zip(distances[0], labels[0])
                         if 0 <= label < self.index.ntotal and int(label) + 1 in allowed]
                # Filter -1 before restoring IDs and deduplicate before limiting to k.
                unique = {row: score for score, row in valid}
                rows = sorted(unique, key=lambda row: (-unique[row], row))[:wanted]
                if len(rows) == wanted:
                    ranked.append(self.table.public_ids(rows))
                    break
                if fetch == self.index.ntotal:
                    raise ValueError('ANN exhausted catalog without required distinct candidates')
                fetch = min(self.index.ntotal, fetch * 2)
        return ranked

    def retrieve(self, context: UserContext, k: int = 300, exclude_purchased: bool = False) -> list[str]:
        return self.search(self.user_vectors([context]), k,
                           context.purchased if exclude_purchased else frozenset())[0]


def flat_reference(model, table, eligible, batch_size):
    """IndexFlatIP uses the identical eligible vectors; labels map through a separate table."""
    import faiss
    reference = ExactCandidate(model, table, eligible, batch_size)
    index = faiss.IndexFlatIP(reference.vectors.shape[1])
    index.add(reference.vectors)
    return reference, index
