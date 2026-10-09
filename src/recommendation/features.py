"""Frozen train-only metadata vocabularies; row indices are never public product IDs."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from src.common.artifacts import fingerprint

ITEM_FIELDS = ('category_l1', 'category_l2', 'category_l3', 'brand', 'color', 'style')
USER_FIELDS = ('age_group', 'gender')
PAD, UNK = 0, 1


def vocabulary(values: pd.Series) -> dict[str, int]:
    return {value: i + 2 for i, value in enumerate(sorted(set(values.dropna().astype(str))))}


@dataclass
class FeatureEncoder:
    """Serializable feature contract v1; no item-ID residual or latent persona inputs."""
    vocabs: dict[str, dict[str, int]]
    price_mean: float
    price_std: float
    fit_cutoff: str
    version: str = 'candidate-features-v1'

    @classmethod
    def fit(cls, products: pd.DataFrame, users: pd.DataFrame, cutoff: pd.Timestamp) -> 'FeatureEncoder':
        known = products[products.created_at <= cutoff]
        if known.empty:
            raise ValueError('no train-available products')
        prices = np.log1p(known.price.to_numpy(dtype=np.float64))
        known_users = users[users.signup_at <= cutoff]
        vocabs = {field: vocabulary(known[field]) for field in ITEM_FIELDS}
        vocabs.update({field: vocabulary(known_users[field]) for field in USER_FIELDS})
        return cls(vocabs, float(prices.mean()), max(float(prices.std()), 1e-6), cutoff.isoformat())

    def to_dict(self) -> dict[str, Any]:
        return dict(version=self.version, vocabs=self.vocabs, price_mean=self.price_mean,
                    price_std=self.price_std, fit_cutoff=self.fit_cutoff,
                    pad=PAD, unknown=UNK, item_id_residual=False,
                    user_fields=list(USER_FIELDS), item_fields=list(ITEM_FIELDS))

    @classmethod
    def from_dict(cls, value: dict) -> 'FeatureEncoder':
        if value['version'] != 'candidate-features-v1' or value['item_id_residual']:
            raise ValueError('unsupported feature contract')
        return cls(value['vocabs'], value['price_mean'], value['price_std'], value['fit_cutoff'])

    @property
    def digest(self) -> str:
        return fingerprint(self.to_dict())

    @property
    def profile_dim(self) -> int:
        return len(self.vocabs['category_l3']) + 2 + len(self.vocabs['brand']) + 2 + 2

    def price(self, values: np.ndarray) -> np.ndarray:
        return ((np.log1p(values) - self.price_mean) / self.price_std).astype(np.float32)

    def item_table(self, products: pd.DataFrame) -> 'ItemTable':
        frame = products.sort_values('product_id', kind='stable').reset_index(drop=True)
        ids = frame.product_id.astype(str).tolist()
        if len(set(ids)) != len(ids):
            raise ValueError('duplicate product IDs')
        cats = np.zeros((len(ids) + 1, len(ITEM_FIELDS)), dtype=np.int64)
        for j, field in enumerate(ITEM_FIELDS):
            cats[1:, j] = frame[field].map(self.vocabs[field]).fillna(UNK).to_numpy(dtype=np.int64)
        prices = np.zeros((len(ids) + 1, 1), dtype=np.float32)
        prices[1:, 0] = self.price(frame.price.to_numpy(dtype=np.float64))
        created = np.concatenate(([np.iinfo(np.int64).max], frame.created_at.astype('int64').to_numpy()))
        return ItemTable(frame, ['<PAD>'] + ids, {pid: i + 1 for i, pid in enumerate(ids)}, cats, prices, created)

    def demographics(self, row: dict | None, at: pd.Timestamp) -> np.ndarray:
        if row is None or pd.Timestamp(row['signup_at']) > at:
            return np.full(2, UNK, dtype=np.int64)
        return np.array([self.vocabs[field].get(str(row[field]), UNK) for field in USER_FIELDS], dtype=np.int64)

    def profile(self, purchased: list[int], table: 'ItemTable') -> np.ndarray:
        cat_n = len(self.vocabs['category_l3']) + 2
        brand_n = len(self.vocabs['brand']) + 2
        result = np.zeros(self.profile_dim, dtype=np.float32)
        if purchased:
            indices = np.asarray(purchased)
            result[:cat_n] = np.bincount(table.categories[indices, 2], minlength=cat_n) / len(indices)
            result[cat_n:cat_n + brand_n] = np.bincount(table.categories[indices, 3], minlength=brand_n) / len(indices)
            result[-2] = table.prices[indices, 0].mean()
            result[-1] = 1.0  # Explicit price-observed flag; zero for users without purchases.
        return result


@dataclass
class ItemTable:
    frame: pd.DataFrame
    ids: list[str]
    id_to_index: dict[str, int]
    categories: np.ndarray
    prices: np.ndarray
    created: np.ndarray

    def eligible(self, at: pd.Timestamp) -> np.ndarray:
        return np.flatnonzero(self.created <= at.value)

    def public_ids(self, indices: np.ndarray | list[int]) -> list[str]:
        if any(int(i) <= 0 or int(i) >= len(self.ids) for i in indices):
            raise ValueError('invalid item row index (PAD/-1 is not a product)')
        return [self.ids[int(i)] for i in indices]
