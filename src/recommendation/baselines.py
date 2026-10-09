"""Popularity fitted on train and explicit observed-history category/brand/price baseline."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.recommendation.datasets import UserContext
from src.recommendation.features import ItemTable


class Baselines:
    def __init__(self, train: pd.DataFrame, table: ItemTable, weights: dict, spec: dict):
        self.table, self.spec = table, spec
        self.counts = np.zeros(len(table.ids), dtype=np.float64)
        self.popularity = np.zeros(len(table.ids), dtype=np.float32)
        for event_type, weight in weights.items():
            counts = train[train.event_type == event_type].product_id.dropna().value_counts()
            for pid, count in counts.items():
                index = table.id_to_index[str(pid)]
                self.popularity[index] += float(count) * weight
                self.counts[index] += int(count)
        self.popularity /= max(float(self.popularity.max()), 1.0)

    def history_scores(self, context: UserContext, eligible: np.ndarray) -> np.ndarray:
        # Uses only observed IDs in the context; the class never receives future truth.
        history = np.asarray(sorted(context.observed), dtype=np.int64)
        if not len(history):
            return self.popularity[eligible].copy()
        categories = self.table.categories
        cat_counts = np.bincount(categories[history, 2], minlength=int(categories[:, 2].max()) + 1) / len(history)
        brand_counts = np.bincount(categories[history, 3], minlength=int(categories[:, 3].max()) + 1) / len(history)
        prices = self.table.prices[:, 0]
        price_affinity = np.exp(-np.abs(prices[eligible] - prices[history].mean()))
        return (self.spec['category_weight'] * cat_counts[categories[eligible, 2]]
                + self.spec['brand_weight'] * brand_counts[categories[eligible, 3]]
                + self.spec['price_weight'] * price_affinity
                + self.spec['popularity_weight'] * self.popularity[eligible])
