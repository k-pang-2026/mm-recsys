"""Generate small live demo batches and update Redis without replaying frozen data."""
from __future__ import annotations

from src.common.console import log, run_cli
import traceback

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
from src.ct.storage import Journal


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
        if 'generated_at' not in events:
            events['generated_at'] = pd.Timestamp.now(tz='UTC')
        temporary = folder / '.pending.parquet'
        events.to_parquet(temporary, index=False)
        temporary.replace(pending)
    category_field = 'category_l3' if 'category_l3' in products else 'category_l1'
    categories = dict(zip(products.product_id, products[category_field]))
    journal = (Journal(Path(cfg['paths']['model_dir']) / '.ct' / 'journal.sqlite3')
               if cfg.get('serving', {}).get('ct', {}).get('enabled', False) else None)
    processed = accepted = 0
    journal_entries = []
    for row in events.itertuples(index=False):
        if row.event_type not in ('view', 'cart', 'purchase') or pd.isna(row.product_id):
            continue
        event = FeedbackRequest(event_id=str(row.event_id), user_id=str(row.user_id),
                                product_id=str(row.product_id), event_type=row.event_type,
                                session_id=str(row.session_id), category=categories.get(row.product_id))
        store.append_event(event)
        store.update_reward(event)
        if journal is not None:
            journal_entries.append((event.model_dump(), pd.Timestamp(row.generated_at).timestamp()))
        processed += 1
    if journal is not None:
        accepted = journal.events(journal_entries)
    archive = folder / f'events-{file_hash(pending)}.parquet'
    if archive.exists():
        raise ValueError('duplicate live log archive; preserve the pending batch for diagnosis')
    pending.rename(archive)
    counts = {str(name): int(count) for name, count in events.event_type.value_counts().items()}
    return dict(generated=len(events), features_processed=processed, ct_new_events=accepted,
                event_types=counts, source=str(archive))


def main() -> None:
    api = os.environ.get('API_URL', 'http://api-server:8000')
    wait_ready(api, float(os.getenv('READY_TIMEOUT_SECONDS', '21600')))
    cfg = runtime_config()
    root = Path(cfg['paths']['data_dir'])
    size = int(os.getenv('SIMULATOR_BATCH_SIZE', '100'))
    interval = float(os.getenv('SIMULATOR_INTERVAL_SECONDS', '5'))
    if not 1 <= size <= 10000 or not np.isfinite(interval) or interval <= 0:
        raise ValueError('live batch size must be 1..10000 and interval must be finite and positive')
    products = pd.read_parquet(root / 'products.parquet')
    users = pd.read_parquet(root / 'users.parquet')
    rng = np.random.default_rng(cfg['seed'])
    store = create_feature_store(cfg)
    if not isinstance(store, RedisFeatureStore):
        raise ValueError('live simulator requires the serving Redis backend')
    log('시뮬레이터', '시작', f'API·대시보드 준비 완료; 배치={size}건 / 주기={interval}초 / 모의 로그 생성·Redis 피처 갱신')
    try:
        while True:
            started = time.monotonic()
            try:
                result = run_batch(cfg, store, products, users, rng, size)
            except (OSError, RedisError) as error:
                log('시뮬레이터', '재시도', f'원인: {type(error).__name__}: {error} / 다음 조치: Redis 연결과 저장 공간을 확인하세요. {interval}초 뒤 같은 배치를 재시도합니다.', status='실패')
                traceback.print_exc()
                delay = interval
            else:
                elapsed = time.monotonic() - started
                log('시뮬레이터', '생성', f"행동 로그 {result['generated']:,}건 생성 / {elapsed:.1f}초 / "
                    f"{result['generated']/max(elapsed, .001):,.0f}건/초 / CT 신규 로그={result['ct_new_events']:,}건", status='성공')
                delay = max(.01, interval - elapsed)
            time.sleep(delay)
    finally:
        store.close()


if __name__ == '__main__':
    run_cli(main, '시뮬레이터', 'API·Redis 연결과 배치 크기·주기 설정을 확인하세요.')
