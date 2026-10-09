"""Exact all-catalog reference retrieval; ANN persistence belongs to B3b."""
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
