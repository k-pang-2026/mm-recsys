"""Generate small live demo batches and update Redis without replaying frozen data."""
from __future__ import annotations

from src.common.console import log, run_cli
import traceback

import copy
from contextlib import suppress
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from types import FrameType
import uuid
from urllib.request import build_opener, ProxyHandler

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
from scripts.ct_api_traffic import visit


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
    visits = int(os.getenv('SIMULATOR_ATTRIBUTED_VISITS', '1'))
    auto_train = os.getenv('CT_AUTO_TRAIN', '1')
    if not 1 <= size <= 10000 or not np.isfinite(interval) or interval <= 0:
        raise ValueError('live batch size must be 1..10000 and interval must be finite and positive')
    if not 0 <= visits <= 100:
        raise ValueError('SIMULATOR_ATTRIBUTED_VISITS must be 0..100')
    if auto_train not in ('0', '1'):
        raise ValueError('CT_AUTO_TRAIN must be 0 or 1')
    if visits and not cfg['serving']['ct']['enabled']:
        raise ValueError('attributed visits require CT; set SIMULATOR_ATTRIBUTED_VISITS=0 to disable')
    products = pd.read_parquet(root / 'products.parquet')
    users = pd.read_parquet(root / 'users.parquet')
    rng = np.random.default_rng(cfg['seed'])
    store = create_feature_store(cfg)
    if not isinstance(store, RedisFeatureStore):
        raise ValueError('live simulator requires the serving Redis backend')
    run_id, visit_index = uuid.uuid4().hex, 0
    output = Path(cfg['paths']['results_dir']) / f'ct_api_traffic_{run_id}.jsonl'
    output.parent.mkdir(parents=True, exist_ok=True)
    opener = build_opener(ProxyHandler({}))
    worker = None
    def stop(signum: int, frame: FrameType | None) -> None:
        raise KeyboardInterrupt
    previous_handler = signal.signal(signal.SIGTERM, stop)
    log('시뮬레이터', '시작', f'API·대시보드 준비 완료; 배치={size}건 / 주기={interval}초 / 합성 추천 흐름={visits}회 / 귀속 로그={output}')
    try:
        if auto_train == '1' and cfg['serving']['ct']['enabled']:
            worker = subprocess.Popen([sys.executable, '-m', 'docker.ct_worker'], start_new_session=True)
            log('시뮬레이터', 'CT 연결', '주기적 모니터링·설정 임계치 기반 재학습을 함께 시작합니다.', status='성공')
        with output.open('x', encoding='utf-8') as stream:
            def record(value: dict) -> None:
                stream.write(json.dumps(dict(run_id=run_id, recorded_at=time.time(), synthetic=True, **value),
                                        ensure_ascii=False, allow_nan=False) + '\n')
                stream.flush()

            record(dict(event='start', api=api, visits_per_batch=visits, top_n=50))
            while True:
                if worker is not None and worker.poll() is not None:
                    raise RuntimeError(f'CT worker exited: {worker.returncode}; inspect the original worker log')
                started = time.monotonic()
                try:
                    result = run_batch(cfg, store, products, users, rng, size)
                    for _ in range(visits):
                        index = visit_index
                        visit_index += 1
                        visit(opener, api, str(users.iloc[index % len(users)].user_id),
                              run_id, index, 50, record)
                except (OSError, RedisError) as error:
                    record(dict(event='error', detail=str(error), visit_index=visit_index))
                    log('시뮬레이터', '재시도', f'원인: {type(error).__name__}: {error} / 다음 조치: API·Redis와 귀속 로그의 intent·ack를 확인하세요. 미완료 Markov 배치는 보존됩니다.', status='실패')
                    traceback.print_exc()
                    delay = interval
                else:
                    elapsed = time.monotonic() - started
                    log('시뮬레이터', '생성', f"행동 로그 {result['generated']:,}건 생성 / {elapsed:.1f}초 / "
                        f"{result['generated']/max(elapsed, .001):,.0f}건/초 / CT 신규 로그={result['ct_new_events']:,}건 / 합성 추천 흐름={visits}회", status='성공')
                    delay = max(.01, interval - elapsed)
                time.sleep(delay)
    finally:
        if worker is not None and worker.poll() is None:
            # The Docker worker owns its demo/trainer process group.
            with suppress(ProcessLookupError):
                os.killpg(worker.pid, signal.SIGTERM)
            try:
                worker.wait(timeout=10)
            except subprocess.TimeoutExpired:
                with suppress(ProcessLookupError):
                    os.killpg(worker.pid, signal.SIGKILL)
                worker.wait()
        signal.signal(signal.SIGTERM, previous_handler)
        store.close()


if __name__ == '__main__':
    run_cli(main, '시뮬레이터', 'API·Redis 연결과 배치 크기·주기 설정을 확인하세요.')
