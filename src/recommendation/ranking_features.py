"""Train-only vocabulary/scalers and strictly preceding observed user features."""
from __future__ import annotations

from typing import Any

from dataclasses import dataclass
import numpy as np
import pandas as pd

from src.common.artifacts import fingerprint
from src.recommendation.features import FeatureEncoder, ITEM_FIELDS, USER_FIELDS

SPARSE_FIELDS = (*USER_FIELDS, *ITEM_FIELDS, 'hour', 'weekday')
DENSE_FIELDS = ('price', 'popularity', 'history_count', 'category_l1_match', 'category_l3_match',
                'brand_match', 'purchase_category_match', 'purchase_brand_match', 'price_difference',
                'price_observed', 'session_count', 'item_age_days')


class HistoryIndex:
    """Per-user cumulative arrays queried with searchsorted(left), including timestamp ties."""
    def __init__(self, events: pd.DataFrame, table, popularity_events: pd.DataFrame | None = None):
        events = events[events.event_type.isin(['view', 'cart', 'purchase']) & events.product_id.notna()]
        self.users = {}
        self.table = table
        for uid, group in events.sort_values(['timestamp', 'event_id']).groupby('user_id', sort=False):
            rows = np.array([table.id_to_index[str(p)] for p in group.product_id], dtype=np.int64)
            cats = table.categories[rows]
            purchase = (group.event_type.to_numpy() == 'purchase').astype(np.float32)
            cumulative = []
            for column, mask in [(0, None), (2, None), (3, None), (2, purchase), (3, purchase)]:
                width = int(table.categories[:, column].max()) + 1
                one_hot = np.zeros((len(rows), width), dtype=np.float32)
                one_hot[np.arange(len(rows)), cats[:, column]] = 1 if mask is None else mask
                cumulative.append(np.vstack([np.zeros((1, width), np.float32), one_hot.cumsum(axis=0)]))
            price_sum = np.r_[0, table.prices[rows, 0].cumsum()]
            purchase_n = np.r_[0, purchase.cumsum()]
            # Current session counts are observable before the target timestamp.
            session_times = {str(sid): values.timestamp.astype('int64').to_numpy()
                             for sid, values in group[group.event_type == 'view'].groupby('session_id')}
            self.users[str(uid)] = (group.timestamp.astype('int64').to_numpy(), cumulative, price_sum, purchase_n, session_times)
        population = events if popularity_events is None else popularity_events[
            popularity_events.event_type.isin(['view', 'cart', 'purchase']) & popularity_events.product_id.notna()]
        self.item_times = {str(pid): g.timestamp.astype('int64').sort_values().to_numpy()
                           for pid, g in population.groupby('product_id', sort=False)}

    def raw(self, user_id: str, rows: np.ndarray, times: np.ndarray,
            session_ids: np.ndarray | None = None) -> np.ndarray:
        cats = self.table.categories[rows]
        result = np.zeros((len(rows), len(DENSE_FIELDS)), np.float32)
        result[:, 0] = self.table.prices[rows, 0]
        for pid in set(self.table.public_ids(rows)):
            mask = rows == self.table.id_to_index[pid]
            result[mask, 1] = np.log1p(np.searchsorted(self.item_times.get(pid, []), times[mask], side='left'))
        value = self.users.get(str(user_id))
        if value:
            event_times, cumulative, price_sum, purchase_n, sessions = value
            count = np.searchsorted(event_times, times, side='left')
            result[:, 2] = np.log1p(count)
            for j, column in enumerate([0, 2, 3, 2, 3]):
                denominator = count if j < 3 else purchase_n[count]
                result[:, 3+j] = cumulative[j][count, cats[:, column]] / np.maximum(denominator, 1)
            result[:, 8] = np.abs(result[:, 0] - price_sum[count] / np.maximum(count, 1)) * (count > 0)
            result[:, 9] = count > 0
            if session_ids is not None:
                for sid in set(session_ids):
                    mask = session_ids == sid
                    result[mask, 10] = np.log1p(np.searchsorted(sessions.get(str(sid), []), times[mask], side='left'))
        result[:, 11] = np.maximum(0, (times - self.table.created[rows]) / pd.Timedelta(days=1).value)
        return result


@dataclass
class RankingEncoder:
    metadata: FeatureEncoder
    mean: np.ndarray
    std: np.ndarray
    cross_features: bool
    version: str = 'deepfm-features-v1'

    @property
    def cardinalities(self) -> list[int]:
        return [len(self.metadata.vocabs[f])+2 for f in (*USER_FIELDS, *ITEM_FIELDS)] + [24, 7]

    @property
    def digest(self) -> str:
        return fingerprint(self.to_dict())

    def to_dict(self) -> dict:
        return dict(version=self.version, metadata=self.metadata.to_dict(), mean=self.mean.tolist(),
                    std=self.std.tolist(), cross_features=self.cross_features,
                    sparse_fields=list(SPARSE_FIELDS), dense_fields=list(DENSE_FIELDS),
                    excluded=['position', 'impression_id', 'request_id', 'event_type', 'persona'])

    @classmethod
    def from_dict(cls, value: dict) -> Any:
        if value['version'] != 'deepfm-features-v1' or value['dense_fields'] != list(DENSE_FIELDS):
            raise ValueError('ranking feature contract mismatch')
        return cls(FeatureEncoder.from_dict(value['metadata']), np.array(value['mean'], np.float32),
                   np.array(value['std'], np.float32), bool(value['cross_features']))

    def transform(self, labels: pd.DataFrame, users: pd.DataFrame, table: Any, history: HistoryIndex,
                  freeze_at: pd.Timestamp | None = None, fit: bool = False,
                  user_rows: dict | None = None) -> tuple[np.ndarray, np.ndarray]:
        sparse = np.zeros((len(labels), len(SPARSE_FIELDS)), np.int64)
        dense = np.zeros((len(labels), len(DENSE_FIELDS)), np.float32)
        if user_rows is None:
            user_rows = users.set_index('user_id').to_dict('index')
        rows = labels.product_id.map(table.id_to_index).to_numpy(dtype=np.int64)
        at = pd.to_datetime(labels.exposed_at)
        if (table.created[rows] > at.astype('int64').to_numpy()).any():
            raise ValueError('ranking exposure before product registration')
        sparse[:, 2:8] = table.categories[rows]
        sparse[:, 8] = at.dt.hour.to_numpy(); sparse[:, 9] = at.dt.dayofweek.to_numpy()
        times = at.astype('int64').to_numpy()
        if freeze_at is not None:
            times = np.minimum(times, freeze_at.value)
        for uid, positions in labels.groupby('user_id', sort=False).indices.items():
            positions = np.asarray(positions)
            demo = self.metadata.demographics(user_rows.get(uid), pd.Timestamp(int(times[positions].min()), tz='UTC'))
            sparse[positions, :2] = demo
            sessions = labels.iloc[positions].session_id.to_numpy() if 'session_id' in labels else None
            dense[positions] = history.raw(str(uid), rows[positions], times[positions], sessions)
        if fit:
            self.mean = dense.mean(axis=0, dtype=np.float64).astype(np.float32)
            self.std = np.maximum(dense.std(axis=0, dtype=np.float64), 1e-6).astype(np.float32)
        dense = (dense - self.mean) / self.std
        if not self.cross_features:
            dense[:, 3:10] = 0
        if not np.isfinite(dense).all():
            raise ValueError('nonfinite ranking features')
        return sparse, dense.astype(np.float32)

    def serving(self, user_id: str, products: list[str], at: pd.Timestamp, users: pd.DataFrame,
                table: Any, history: HistoryIndex, recent_clicks: list[str], session_count: int,
                user_rows: dict | None = None) -> tuple[np.ndarray, np.ndarray]:
        labels = pd.DataFrame(dict(user_id=[user_id]*len(products), product_id=products, exposed_at=[at]*len(products)))
        sparse, dense = self.transform(labels, users, table, history, user_rows=user_rows)
        # Online session views augment observed affinities; current request is never an input label.
        known = [table.id_to_index[p] for p in recent_clicks if p in table.id_to_index and table.created[table.id_to_index[p]] <= at.value]
        raw = dense * self.std + self.mean
        if known:
            rows = np.array([table.id_to_index[p] for p in products]); cats = table.categories
            for field, target in [(0, 3), (2, 4), (3, 5)]:
                counts = np.bincount(cats[known, field], minlength=int(cats[:, field].max())+1) / len(known)
                raw[:, target] = counts[cats[rows, field]]
            raw[:, 8] = np.abs(table.prices[rows, 0] - table.prices[known, 0].mean())
            raw[:, 9] = 1
        raw[:, 10] = np.log1p(session_count)
        dense = (raw-self.mean)/self.std
        if not self.cross_features: dense[:, 3:10] = 0
        return sparse, dense.astype(np.float32)
