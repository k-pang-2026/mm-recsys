"""Linked-view CTR and last preceding same-session view purchase attribution."""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

from src.common.artifacts import file_hash


def read_impressions(root: str | Path, manifest: dict) -> pd.DataFrame:
    path = Path(root) / 'impressions.parquet'
    if file_hash(path) != manifest['file_hashes']['impressions.parquet']:
        raise ValueError('impressions checksum mismatch')
    return pd.read_parquet(path)


def build_labels(impressions: pd.DataFrame, events: pd.DataFrame, start: pd.Timestamp,
                 end: pd.Timestamp, window_seconds: int) -> tuple[pd.DataFrame, dict]:
    if window_seconds <= 0 or end < start:
        raise ValueError('invalid observation window')
    if impressions.impression_id.duplicated().any() or events.event_id.duplicated().any():
        raise ValueError('duplicate impression/event ID')
    observed = events[events.timestamp <= end]
    views = observed[(observed.event_type == 'view') & observed.impression_id.notna()].copy()
    # One exposure may receive repeated clicks; CTR is binary, attribution uses the last raw view.
    linked = views.merge(impressions, on='impression_id', suffixes=('_event', '_exposure'), validate='many_to_one')
    if len(linked) != len(views):
        raise ValueError('unlinked view impression')
    if ((linked.user_id_event != linked.user_id_exposure) |
        (linked.product_id_event != linked.product_id_exposure) |
        (linked.timestamp < linked.exposed_at)).any():
        raise ValueError('invalid view linkage')
    valid_views = linked[linked.timestamp <= linked.exposed_at + pd.Timedelta(seconds=window_seconds)]
    purchases = observed[(observed.event_type == 'purchase') & observed.product_id.notna()]
    right = views[['user_id', 'product_id', 'session_id', 'timestamp', 'impression_id']].sort_values('timestamp')
    left = purchases[['user_id', 'product_id', 'session_id', 'timestamp', 'event_id']].sort_values('timestamp')
    if len(left) and len(right):
        attributed = pd.merge_asof(left, right, on='timestamp', by=['user_id', 'product_id', 'session_id'],
                                   tolerance=pd.Timedelta(seconds=window_seconds), direction='backward',
                                   allow_exact_matches=False)
    else:
        attributed = left.assign(impression_id=None)
    positive = set(attributed.impression_id.dropna())
    labels = impressions[(impressions.exposed_at >= start) & (impressions.exposed_at <= end)].copy()
    session_map = valid_views.drop_duplicates('request_id').set_index('request_id').session_id
    labels['session_id'] = labels.request_id.map(session_map).fillna('unknown')
    labels['ctr'] = labels.impression_id.isin(set(valid_views.impression_id)).astype(np.float32)
    labels['cvr'] = labels.impression_id.isin(positive).astype(np.float32)
    # Never label an incompletely observed negative as a known non-conversion.
    mature = labels.exposed_at + pd.Timedelta(seconds=window_seconds) <= end
    labels['ctr_mask'] = (labels.ctr == 1) | mature
    labels['cvr_mask'] = (labels.ctr == 1) & ((labels.cvr == 1) | mature)
    labels['censored'] = ~mature
    if ((labels.cvr == 1) & (labels.ctr != 1)).any():
        raise ValueError('purchase attributed outside a linked clicked exposure')
    diagnostics = dict(version='linked-view-last-view-v2', rows=len(labels), clicks=int(labels.ctr.sum()),
                       conversions=int(labels.cvr.sum()), ctr_observed=int(labels.ctr_mask.sum()),
                       cvr_observed=int(labels.cvr_mask.sum()), censored=int(labels.censored.sum()),
                       censored_cvr_negatives=int(((labels.ctr == 1) & ~labels.cvr_mask).sum()),
                       unassigned_purchases=int(attributed.impression_id.isna().sum()),
                       window_seconds=window_seconds, start=start.isoformat(), end=end.isoformat(),
                       ctr_proxy='linked view; generator timestamps equal exposure timestamps',
                       cvr_denominator='observed linked clicked exposures only',
                       same_timestamp_view_exposure=int((linked.timestamp == linked.exposed_at).sum()),
                       excluded_inputs=['position', 'impression_id', 'request_id', 'event_type', 'persona'])
    return labels.reset_index(drop=True), diagnostics
