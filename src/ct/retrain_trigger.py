"""Serialized event-threshold training; failures never consume events or replace active models."""
from __future__ import annotations

from typing import Any

import argparse
import copy
import json
from pathlib import Path
import time

from src.common.artifacts import write_json
from src.common.config import load_config
from src.ct.model_registry import ModelRegistry
from src.ct.storage import Journal, append_log, file_lock


def settings(cfg: dict) -> dict:
    spec = copy.deepcopy(cfg['serving']['ct'])
    spec.setdefault('hitrate_threshold', cfg['ct']['hitrate_threshold'])
    spec.setdefault('retrain_log_threshold', cfg['ct']['retrain_log_threshold'])
    for key in ('poll_seconds', 'recent_seconds', 'attribution_seconds', 'min_mature_requests', 'retrain_log_threshold'):
        if float(spec[key]) <= 0:
            raise ValueError(f'CT {key} must be positive')
    return spec


def components(cfg: dict) -> tuple[dict, Journal, ModelRegistry]:
    spec = settings(cfg)
    return (spec, Journal(Path(cfg['paths']['model_dir']) / '.ct' / 'journal.sqlite3'),
            ModelRegistry(Path(cfg['paths']['model_dir']), Path(cfg['paths']['results_dir']) / 'ct_log.jsonl'))


def trigger(cfg: dict, build: Any) -> dict:
    spec, journal, registry = components(cfg)
    try:
        with file_lock(registry.root / '.ct' / 'training.lock', blocking=False):
            state = registry.read(); through = journal.high_watermark()
            count = journal.count_since(state['last_success_seq'], through)
            if count < int(spec['retrain_log_threshold']):
                return dict(status='WAITING', new_events=count, threshold=spec['retrain_log_threshold'])
            if not state['active']:
                raise ValueError('register and initialize v1.0 before retraining')
            parent, version = state['active'], registry.next_version()
            append_log(registry.log, dict(event='training_started', parent=parent, version=version,
                                          new_events=count, through_seq=through))
            try:
                # build must only include journal events through this captured watermark.
                result = build(version, through, registry)
                registry.register(version, result['config'], Path(result['data_path']),
                                  result['comparison']['candidate'], parent, through)
                promoted = registry.decide(version, result['comparison'], spec)
                return dict(status='PROMOTED' if promoted else 'RETAINED', version=version,
                            active=registry.read()['active'], new_events=count, through_seq=through,
                            comparison=result['comparison'])
            except Exception as error:
                append_log(registry.log, dict(event='training_failed', version=version,
                                              error=f'{type(error).__name__}: {error}'))
                raise
    except BlockingIOError:
        return dict(status='BUSY')


def build_from_journal(cfg: dict, version: str, through: int, registry: ModelRegistry) -> dict:
    import pandas as pd
    from src.ct.training import snapshot, train_all, validation
    from src.serving.model_loader import load_record
    from src.serving.memory_store import MemoryFeatureStore
    from src.common.artifacts import file_hash
    spec, journal, _ = components(cfg)
    parent = registry.record(registry.read()['active'])
    source = Path(parent['data_path'])
    with journal.connect() as db:
        rows = db.execute('SELECT * FROM events WHERE seq>? AND seq<=? ORDER BY seq',
                           (parent['trained_through_seq'], through)).fetchall()
        requests = db.execute('SELECT * FROM requests').fetchall()
    events = pd.read_parquet(source / 'events.parquet')
    incoming = []
    for row in rows:
        payload = json.loads(row['payload'])
        incoming.append(dict(event_id=row['id'], user_id=row['user_id'], product_id=row['product_id'],
                             event_type=row['kind'], timestamp=pd.Timestamp(row['at'], unit='s', tz='UTC'),
                             session_id=payload.get('session_id', 'default'), query=None,
                             impression_id=f"{row['request_id']}:{row['product_id']}" if row['request_id'] else None,
                             position=None))
    events = pd.concat([events, pd.DataFrame(incoming)], ignore_index=True).drop_duplicates('event_id')
    existing = pd.read_parquet(source / 'impressions.parquet')
    exposures = [dict(impression_id=f"{r['id']}:{pid}", request_id=r['id'], user_id=r['user_id'],
                      product_id=pid, exposed_at=pd.Timestamp(r['at'], unit='s', tz='UTC'), position=i + 1)
                 for r in requests for i, pid in enumerate(json.loads(r['items']))]
    impressions = pd.concat([existing, pd.DataFrame(exposures)], ignore_index=True).drop_duplicates('impression_id')
    # A failed attempt is kept for diagnosis; select a fresh unique workspace on retry.
    import uuid
    work = registry.root / '.ct' / 'runs' / f'{version}-{uuid.uuid4().hex[:8]}'
    data_path = work / 'data'
    manifest = snapshot(source, data_path, events, impressions, cfg)
    local = copy.deepcopy(cfg); local['paths']['data_dir'] = str(data_path)
    local['simulator']['reference_time'] = (pd.Timestamp(manifest['observed_through']) + pd.Timedelta(microseconds=1)).isoformat()
    reports, bundle = train_all(local, work)
    bundle.rename(registry.root / version)
    # Temporary standalone registry uses the same production loaders before registration.
    staged = ModelRegistry(work / 'probe', work / 'probe.jsonl')
    staged.root.mkdir(parents=True)
    (staged.root / version).symlink_to(registry.root / version, target_is_directory=True)
    staged.register(version, local, data_path, {}, None, through)
    baseline = validation(load_record(registry, parent['version'], MemoryFeatureStore()), local)
    candidate = validation(load_record(staged, version, MemoryFeatureStore()), local)
    if baseline['validation_fingerprint'] != candidate['validation_fingerprint']:
        raise ValueError('paired validation cohort changed')
    comparison = dict(split='valid', validation_fingerprint=candidate['validation_fingerprint'],
                      baseline=baseline, candidate=candidate,
                      training_reports={key: file_hash(work / 'results' / name) for key, name in
                         [('candidate', f'candidate_training_{cfg["scale"]}.json'),
                          ('ranking', f'ranking_training_{cfg["scale"]}.json'),
                          ('session', f'session_training_{cfg["scale"]}.json')]})
    write_json(work / 'comparison.json', comparison)
    return dict(config=local, data_path=str(data_path), comparison=comparison)


def reload_api(url: str, version: str) -> dict:
    from urllib.parse import urlparse
    import ipaddress
    import requests
    parsed = urlparse(url)
    try:
        loopback = parsed.hostname == 'localhost' or ipaddress.ip_address(parsed.hostname or '').is_loopback
    except ValueError:
        loopback = False
    if (not loopback or parsed.scheme != 'http' or parsed.username or parsed.password
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise ValueError('reload URL must be a direct local HTTP API origin')
    with requests.Session() as session:
        session.trust_env = False
        response = session.post(url.rstrip('/') + '/api/admin/reload', json=dict(version=version),
                                timeout=60, allow_redirects=False)
    if response.status_code != 200:
        raise RuntimeError(f'active registry changed but API reload failed: HTTP {response.status_code}; retry reload')
    return response.json()


def main() -> int:
    parser = argparse.ArgumentParser(description='Local CT monitor / explicitly enabled retraining worker')
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--rollback', metavar='VERSION')
    parser.add_argument('--reason', default='explicit operator rollback')
    parser.add_argument('--reload-url', help='optional direct loopback API URL after promotion/rollback')
    parser.add_argument('--train', action='store_true', help='train only when event threshold is met')
    args = parser.parse_args(); cfg = load_config()
    from src.ct.monitor import monitor
    spec, journal, registry = components(cfg)
    if args.rollback:
        if args.watch or args.train:
            parser.error('--rollback cannot be combined with --watch or --train')
        state = registry.read()
        registry.rollback(state['active'], args.rollback, args.reason)
        if args.reload_url:
            reload_api(args.reload_url, args.rollback)
        print(json.dumps(dict(status='ROLLED_BACK', active=registry.read()['active'])))
        return 0
    while True:
        monitor(journal, spec, time.time(), registry.log)
        if args.train:
            result = trigger(cfg, lambda version, through, reg: build_from_journal(cfg, version, through, reg))
            print(json.dumps(result), flush=True)
            if result['status'] == 'PROMOTED' and args.reload_url:
                reload_api(args.reload_url, result['active'])
        if not args.watch:
            break
        time.sleep(float(spec['poll_seconds']))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
