"""Replay generated outcomes through API/CT interfaces after preparation; no generation."""
from __future__ import annotations

from typing import Any

import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError
from typing import cast

import pandas as pd
from redis.exceptions import RedisError

from src.common.artifacts import write_json
from docker.http import request, wait_ready
from docker.runtime import runtime_config


def read_checkpoint(client: Any, key: str, identity: str, total: int) -> dict:
    raw = client.get(key)
    state = json.loads(raw) if raw else dict(data_fingerprint=identity, offset=0)
    if state.get('data_fingerprint') != identity or type(state.get('offset')) is not int or not 0 <= state['offset'] <= total:
        raise ValueError('simulator checkpoint does not match the frozen dataset')
    return state


def send_rows(api: str, rows: Any, categories: dict) -> None:
    """Checkpoint advances only after both writes; duplicate retries retain event IDs."""
    for row in rows.itertuples(index=False):
        if row.event_type not in ('view', 'cart', 'purchase') or pd.isna(row.product_id):
            continue
        payload = dict(event_id=str(row.event_id), user_id=str(row.user_id), product_id=str(row.product_id),
                       event_type=row.event_type, session_id=str(row.session_id),
                       category=categories.get(row.product_id))
        request(api + '/api/event', payload)
        request(api + '/api/feedback', payload)


def main() -> None:
    api = os.environ.get('API_URL', 'http://api-server:8000')
    wait_ready(api, float(os.getenv('READY_TIMEOUT_SECONDS', '21600')))
    cfg = runtime_config()
    root = Path(cfg['paths']['data_dir'])
    manifest = json.loads((root / 'split_manifest.json').read_text())
    events = pd.read_parquet(root / 'events.parquet', columns=[
        'event_id', 'user_id', 'product_id', 'event_type', 'session_id', 'timestamp'
    ]).sort_values(['timestamp', 'event_id'], kind='stable')
    products = pd.read_parquet(root / 'products.parquet', columns=['product_id', 'category_l1'])
    categories = dict(zip(products.product_id, products.category_l1))
    from src.serving.feature_store import RedisFeatureStore, create_feature_store
    store = create_feature_store(cfg)
    if not isinstance(store, RedisFeatureStore):
        raise ValueError('simulator checkpoint requires the serving Redis backend')
    # Persist with Redis state: a fresh backend must not skip a former backend's events.
    key = store.key('simulator_checkpoint', manifest['generation_fingerprint'])
    saved = read_checkpoint(store.client, key, manifest['generation_fingerprint'], len(events))
    run_id = cast(dict, store.client.info('server'))['run_id']
    cursor = root / 'stream' / f'docker_cursor_{run_id}.json'
    batch = int(os.getenv('SIMULATOR_BATCH_SIZE', '100'))
    interval = float(os.getenv('SIMULATOR_INTERVAL_SECONDS', '5'))
    if batch < 1 or interval <= 0:
        raise ValueError('positive simulator batch and interval required')
    offset = int(saved['offset'])
    while True:
        try:
            rows = events.iloc[offset:offset+batch]
            send_rows(api, rows, categories)
            next_offset = offset+len(rows)
            state = dict(data_fingerprint=manifest['generation_fingerprint'], offset=next_offset,
                         scope='synthetic replay in chronological order; API arrival clock; no exposure attribution')
            store.client.set(key, json.dumps(state))
            write_json(cursor, state)
        except HTTPError as error:
            if error.code < 500:
                raise
            print(f'API replay retry at {offset}: HTTP {error.code}', flush=True)
        except (OSError, RedisError) as error:
            print(f'API replay retry at {offset}: {type(error).__name__}', flush=True)
        else:
            offset = next_offset
            print(f'synthetic API replay: {offset}/{len(events)}', flush=True)
        time.sleep(interval)


if __name__ == '__main__':
    main()
