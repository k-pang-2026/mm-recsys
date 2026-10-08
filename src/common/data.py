"""Consumers use this adapter rather than assuming arbitrary parquet column types."""
from __future__ import annotations

import json
from pathlib import Path
import pandas as pd
from src.common.artifacts import file_hash


def load_dataset(root: str | Path, verify: bool = True) -> dict:
    root=Path(root);manifest=json.loads((root/'split_manifest.json').read_text())
    if verify:
        for name,digest in manifest['file_hashes'].items():
            if file_hash(root/name)!=digest:raise ValueError(f'dataset checksum mismatch: {name}')
    return {'products':pd.read_parquet(root/'products.parquet'),
            'users':pd.read_parquet(root/'users.parquet'),
            'impressions':pd.read_parquet(root/'impressions.parquet'),
            'splits':{name:pd.read_parquet(root/f'split/{name}.parquet') for name in ['train','valid','test']},
            'manifest':manifest}


def history_before(events: pd.DataFrame, user_id: str, cutoff: pd.Timestamp, limit: int) -> pd.DataFrame:
    return events[(events.user_id==user_id)&(events.timestamp<cutoff)&events.product_id.notna()].sort_values(
        ['timestamp','event_id'],kind='stable').tail(limit).copy()
