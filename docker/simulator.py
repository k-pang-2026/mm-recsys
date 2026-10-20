"""Generate small live demo batches and update Redis without replaying frozen data."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import time
import uuid

import numpy as np
import pandas as pd
from redis.exceptions import RedisError

from docker.http import wait_ready
from docker.runtime import runtime_config
from src.common.artifacts import file_hash
from src.common.schemas import FeedbackRequest
from src.serving.feature_store import RedisFeatureStore, create_feature_store
from src.simulator.events import make_events


def generate_batch(cfg: dict, products: pd.DataFrame, users: pd.DataFrame,
                   rng: np.random.Generator, size: int) -> pd.DataFrame:
    local = copy.deepcopy(cfg)
    local['simulator'].update(n_users=1, n_events=size)
    selected = users.iloc[[int(rng.integers(len(users)))]]
    events, _ = make_events(local, products, selected, rng)
    prefix = 'live-' + uuid.uuid4().hex + '-'
    for name in ('event_id', 'session_id', 'impression_id'):
        events[name] = events[name].map(lambda value: prefix + value if pd.notna(value) else value)
    events['generated_at'] = pd.Timestamp.now(tz='UTC')
    return events


def run_batch(cfg: dict, store: RedisFeatureStore, products: pd.DataFrame, users: pd.DataFrame,
              rng: np.random.Generator, size: int) -> dict:
    root = Path(cfg['paths']['data_dir'])
    identity = json.loads((root / 'split_manifest.json').read_text())['generation_fingerprint']
    folder = root / 'stream' / 'live' / identity
    folder.mkdir(parents=True, exist_ok=True)
    pending = folder / 'pending.parquet'
    if pending.exists():
        events = pd.read_parquet(pending)
    else:
        events = generate_batch(cfg, products, users, rng, size)
        temporary = folder / '.pending.parquet'
        events.to_parquet(temporary, index=False)
        temporary.replace(pending)
    categories = dict(zip(products.product_id, products.category_l1))
    processed = 0
    for row in events.itertuples(index=False):
        if row.event_type not in ('view', 'cart', 'purchase') or pd.isna(row.product_id):
            continue
        event = FeedbackRequest(event_id=str(row.event_id), user_id=str(row.user_id),
                                product_id=str(row.product_id), event_type=row.event_type,
                                session_id=str(row.session_id), category=categories.get(row.product_id))
        store.append_event(event)
        store.update_reward(event)
        processed += 1
    archive = folder / f'events-{file_hash(pending)}.parquet'
    if archive.exists():
        raise ValueError('duplicate live log archive; preserve the pending batch for diagnosis')
    pending.rename(archive)
    counts = {str(name): int(count) for name, count in events.event_type.value_counts().items()}
    return dict(generated=len(events), features_processed=processed,
                event_types=counts, source=str(archive))


def main() -> None:
    api = os.environ.get('API_URL', 'http://api-server:8000')
    wait_ready(api, float(os.getenv('READY_TIMEOUT_SECONDS', '21600')))
    cfg = runtime_config()
    root = Path(cfg['paths']['data_dir'])
    size = int(os.getenv('SIMULATOR_BATCH_SIZE', '100'))
    interval = float(os.getenv('SIMULATOR_INTERVAL_SECONDS', '5'))
    if not 1 <= size <= 1000 or not np.isfinite(interval) or interval <= 0:
        raise ValueError('live batch size must be 1..1000 and interval must be finite and positive')
    products = pd.read_parquet(root / 'products.parquet')
    users = pd.read_parquet(root / 'users.parquet')
    rng = np.random.default_rng(cfg['seed'])
    store = create_feature_store(cfg)
    if not isinstance(store, RedisFeatureStore):
        raise ValueError('live simulator requires the serving Redis backend')
    print('[simulator] API·대시보드 준비 완료; 행동 로그 생성 시작 '
          '(소량 모의 로그 생성·Redis 피처 갱신)', flush=True)
    try:
        while True:
            try:
                result = run_batch(cfg, store, products, users, rng, size)
            except (OSError, RedisError) as error:
                print(f'[simulator] 생성 로그 피처 처리 재시도: {type(error).__name__}', flush=True)
            else:
                print(f"[simulator] 행동 로그 {result['generated']}건 생성; "
                      f"Redis 피처 {result['features_processed']}건 처리; 유형 {result['event_types']}", flush=True)
            time.sleep(interval)
    finally:
        store.close()


if __name__ == '__main__':
    main()
