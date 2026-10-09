"""Timestamp-safe observed histories and random 1:4 negative training samples."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset

from src.common.artifacts import file_hash
from src.recommendation.features import FeatureEncoder, ItemTable


def read_data(root: str | Path, split: str = 'valid') -> dict:
    """B3a reads train/valid only. Test requires an explicit split request."""
    if split not in ('valid', 'test'):
        raise ValueError('split must be valid or test')
    root = Path(root)
    manifest = json.loads((root / 'split_manifest.json').read_text())
    names = ['products.parquet', 'users.parquet', 'split/train.parquet', 'split/valid.parquet']
    if split == 'test':
        names.append('split/test.parquet')
    for name in names:
        if file_hash(root / name) != manifest['file_hashes'][name]:
            raise ValueError(f'dataset checksum mismatch: {name}')
    data = {'products': pd.read_parquet(root / names[0]), 'users': pd.read_parquet(root / names[1]),
            'train': pd.read_parquet(root / names[2]), 'valid': pd.read_parquet(root / names[3]),
            'manifest': manifest}
    if split == 'test':
        data['test'] = pd.read_parquet(root / 'split/test.parquet')
    return data


def cutoff_for(data: dict, split: str) -> pd.Timestamp:
    if split not in ('valid', 'test'):
        raise ValueError('split must be valid or test')
    return pd.Timestamp(data['manifest']['boundaries']['train' if split == 'valid' else 'valid']['end'])


def padded_history(history: list[int], n: int) -> np.ndarray:
    result = np.zeros(n, dtype=np.int64)
    recent = history[-n:]
    if recent:
        result[-len(recent):] = recent
    return result


@dataclass
class UserContext:
    history: np.ndarray
    demographics: np.ndarray
    profile: np.ndarray
    observed: frozenset[int]
    purchased: frozenset[int]
    history_count: int


def context_for(history: pd.DataFrame, user: dict | None, encoder: FeatureEncoder,
                table: ItemTable, cutoff: pd.Timestamp, n: int) -> UserContext:
    prior = history[(history.timestamp < cutoff) & history.event_type.isin(['view', 'cart', 'purchase'])
                    & history.product_id.notna()].sort_values(['timestamp', 'event_id'], kind='stable')
    indices = [table.id_to_index[str(pid)] for pid in prior.product_id]
    purchases = [table.id_to_index[str(pid)] for pid in prior[prior.event_type == 'purchase'].product_id]
    return UserContext(padded_history(indices, n), encoder.demographics(user, cutoff),
                       encoder.profile(purchases, table), frozenset(indices), frozenset(purchases), len(indices))


class NegativeSampler:
    def __init__(self, table: ItemTable, seed: int, count: int = 4):
        if count != 4:
            raise ValueError('required random negative ratio is exactly 1:4')
        self.table, self.rng, self.count = table, np.random.default_rng(seed), count
        self.order = np.argsort(table.created, kind='stable')
        self.times = table.created[self.order]
        self.collisions = self.small_pool = self.calls = 0

    def sample(self, at: pd.Timestamp, excluded: set[int]) -> np.ndarray:
        eligible = self.order[:np.searchsorted(self.times, at.value, side='right')]
        self.calls += 1
        # Sparse exclusions: rejection is uniform over the eligible allowed catalog.
        picked: list[int] = []
        for _ in range(64):
            draws = self.rng.choice(eligible, size=8, replace=True)
            for value in draws:
                value = int(value)
                if value in excluded or value in picked:
                    self.collisions += 1
                    continue
                picked.append(value)
                if len(picked) == self.count:
                    return np.asarray(picked, dtype=np.int64)
        allowed = np.array([i for i in eligible if int(i) not in excluded], dtype=np.int64)
        if not len(allowed):
            raise ValueError('no observable valid negative; sample cannot be trained')
        self.small_pool += int(len(allowed) < self.count)
        return self.rng.choice(allowed, self.count, replace=len(allowed) < self.count)

    def diagnostics(self) -> dict:
        return dict(random_negatives_per_positive=4, calls=self.calls, rejected_draws=self.collisions,
                    replacement_small_pool_samples=self.small_pool,
                    impossible_pool_policy='raise; never silently skip',
                    small_pool_policy='uniform with replacement; duplicate counts retained',
                    resampling='fixed independent random draws for each sample, reused across epochs',
                    exclusion='current + strictly previous view/cart/purchase; no future labels',
                    in_batch_negatives=False, hard_negatives=False)


class TrainingDataset(Dataset):
    def __init__(self, events: pd.DataFrame, users: pd.DataFrame, encoder: FeatureEncoder,
                 table: ItemTable, cfg: dict):
        spec = cfg['recommend']['candidate']
        if events.timestamp.max() > pd.Timestamp(encoder.fit_cutoff):
            raise ValueError('training events extend beyond frozen train cutoff')
        weights = spec['positive_weights']
        sampler = NegativeSampler(table, int(cfg['seed']) + 1, spec['negatives_per_positive'])
        user_rows = users.set_index('user_id').to_dict('index')
        histories, demographics, profiles, items, sample_weights = [], [], [], [], []
        timestamps, latest_history, event_ids = [], [], []
        ordered = events.sort_values(['timestamp', 'event_id'], kind='stable')
        for user_id, group in ordered.groupby('user_id', sort=True):
            history: list[int] = []
            purchases: list[int] = []
            seen: set[int] = set()
            latest = np.iinfo(np.int64).min
            # All samples in a timestamp group see the same strictly preceding state.
            for at, simultaneous in group.groupby('timestamp', sort=True):
                snapshot = padded_history(history, spec['history_n'])
                profile = encoder.profile(purchases, table)
                demo = encoder.demographics(user_rows.get(user_id), at)
                additions = []
                for row in simultaneous.itertuples(index=False):
                    if row.event_type not in weights or pd.isna(row.product_id):
                        continue
                    positive = table.id_to_index[str(row.product_id)]
                    if table.created[positive] > at.value:
                        raise ValueError('positive product not registered at event time')
                    negatives = sampler.sample(at, seen | {positive})
                    histories.append(snapshot); demographics.append(demo); profiles.append(profile)
                    items.append(np.concatenate(([positive], negatives)))
                    sample_weights.append(weights[row.event_type])
                    timestamps.append(at.value); latest_history.append(latest); event_ids.append(str(row.event_id))
                    additions.append((positive, row.event_type))
                for positive, event_type in additions:
                    history.append(positive); seen.add(positive)
                    if event_type == 'purchase':
                        purchases.append(positive)
                if additions:
                    latest = at.value
        if not items:
            raise ValueError('no training positives')
        self.history = torch.from_numpy(np.stack(histories))
        self.demographics = torch.from_numpy(np.stack(demographics))
        self.profile = torch.from_numpy(np.stack(profiles))
        self.items = torch.from_numpy(np.stack(items))
        self.weights = torch.tensor(sample_weights, dtype=torch.float32)
        self.timestamps = np.asarray(timestamps, dtype=np.int64)
        self.latest_history = np.asarray(latest_history, dtype=np.int64)
        self.event_ids = event_ids
        self.diagnostics = sampler.diagnostics()
        self.diagnostics.update(samples=len(items), strictly_preceding_history=bool((self.latest_history < self.timestamps).all()))

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int) -> dict[str, torch.Tensor]:
        return dict(history=self.history[index], demographics=self.demographics[index],
                    profile=self.profile[index], items=self.items[index], weights=self.weights[index])
