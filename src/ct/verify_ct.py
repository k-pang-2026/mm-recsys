"""Reproducible small controlled B9 run; never reports full-model acceptance."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import shutil
import socket
import threading
import time
import uuid

import pandas as pd
import requests  # type: ignore[import-untyped]
import torch
import uvicorn

from src.common.artifacts import file_hash, write_json
from src.common.config import load_config
from src.ct.bootstrap import bootstrap
from src.ct.monitor import monitor
from src.ct.retrain_trigger import build_from_journal, components, trigger
from src.ct.storage import Journal, file_lock
from src.ct.training import snapshot, train_all
from src.serving.main import create_app
from src.serving.memory_store import MemoryFeatureStore
from src.simulator.generate import generate


def verify(work: Path, output: Path) -> dict:
    if work.exists():
        raise ValueError('choose a fresh work directory; previous evidence is never overwritten')
    cfg = load_config(); cfg['simulator'].update(n_products=400, n_users=24, n_events=6000, image_size=32)
    cfg['recommend']['candidate'].update(epochs=3, threads=1)
    cfg['recommend']['ranking'].update(epochs=20, batch_size=128, threads=1)
    cfg['recommend']['session']['epochs'] = 3
    cfg['paths'].update(model_dir=str(work / 'models'), results_dir=str(work / 'results'))
    cfg['serving']['feature_store'] = 'memory'
    cfg['serving']['ct']['retrain_log_threshold'] = 200
    source = work / 'source'; source_manifest = generate(cfg, source)
    events = pd.read_parquet(source / 'events.parquet').sort_values(['timestamp', 'event_id'])
    impressions = pd.read_parquet(source / 'impressions.parquet')
    initial = events.iloc[:5000]
    initial_data = work / 'initial_data'
    snapshot(source, initial_data, initial, impressions, cfg)
    cfg['paths']['data_dir'] = str(initial_data)
    _, trained = train_all(cfg, work / 'initial_training')
    root = Path(cfg['paths']['model_dir']); root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(trained, root / 'v1.0')
    # Deliberately weak INITIAL fixture only: constant ranker, measured AUC=0.5.
    # Candidate v1.1 is trained normally. No metric or improvement is injected.
    rank_path = root / 'v1.0/ranking'
    state = torch.load(rank_path / 'deepfm.pt', map_location='cpu', weights_only=True)
    torch.save({key: torch.zeros_like(value) for key, value in state.items()}, rank_path / 'deepfm.pt')
    meta = json.loads((rank_path / 'meta.json').read_text())
    meta['hashes']['deepfm.pt'] = file_hash(rank_path / 'deepfm.pt'); write_json(rank_path / 'meta.json', meta)
    bootstrap(cfg)
    spec, journal, registry = components(cfg)
    # Import the additional observed simulator stream through the public journal contract.
    future = events.iloc[5000:]
    future_impressions = impressions[impressions.exposed_at > initial.timestamp.max()]
    request_for = impressions.set_index('impression_id').request_id.to_dict()
    for rid, group in future_impressions.groupby('request_id'):
        journal.exposure(str(rid), str(group.user_id.iloc[0]), group.product_id.astype(str).tolist(),
                         len(group), 'v1.0', group.exposed_at.iloc[0].timestamp())
    accepted = 0
    for row in future.itertuples(index=False):
        if row.event_type not in ('view', 'cart', 'purchase') or pd.isna(row.product_id):
            continue
        payload = dict(event_id=str(row.event_id), user_id=str(row.user_id), product_id=str(row.product_id),
                       event_type=row.event_type, session_id=str(row.session_id))
        request_id = str(request_for[row.impression_id]) if row.event_type == 'view' else None
        accepted += journal.event(payload, row.timestamp.timestamp(), request_id, spec['attribution_seconds'])
    assert accepted >= spec['retrain_log_threshold']
    # Exercise periodic monitor alert with explicit top50 exposure and a mature zero-outcome window.
    monitor_journal = Journal(work / 'monitor.sqlite3')
    monitor_journal.exposure('controlled-top50', 'u', [f'P{i:06d}' for i in range(1, 51)], 50, 'v1.0', 10.)
    monitor_spec = dict(spec, min_mature_requests=1, attribution_seconds=10, recent_seconds=100)
    alert = monitor(monitor_journal, monitor_spec, 30., registry.log)
    assert len(alert['alerts']) == 2
    with file_lock(registry.root / '.ct/training.lock'):
        busy = trigger(cfg, lambda *args: None)
    assert busy['status'] == 'BUSY'
    # Start a real local API using the registered initial bundle, then train while it serves.
    class SearchFixture:
        def search(self, payload):
            raise RuntimeError('search outside controlled CT scope')
    app = create_app(cfg, search_service=SearchFixture(), feature_store=MemoryFeatureStore())
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level='warning', proxy_headers=False))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True); thread.start()
    api = requests.Session(); api.trust_env = False
    url = f'http://127.0.0.1:{port}'
    try:
        for _ in range(200):
            if server.started:
                break
            if not thread.is_alive():
                raise RuntimeError('API startup failed')
            time.sleep(.05)
        assert server.started
        before = api.get(url + '/api/recommend', params={'user_id': 'unknown'}, timeout=10)
        assert before.status_code == 200 and len(before.json()['recommendations']) == 10
        promoted = trigger(cfg, lambda version, through, reg: build_from_journal(cfg, version, through, reg))
        assert promoted['status'] == 'PROMOTED', promoted
        assert registry.read()['active'] == 'v1.1'
        statuses = []
        def traffic():
            with requests.Session() as session:
                session.trust_env = False
                for _ in range(40):
                    response = session.get(url + '/api/recommend', params={'user_id': 'unknown'}, timeout=10)
                    statuses.append(response.status_code)
        caller = threading.Thread(target=traffic); caller.start()
        reloaded = api.post(url + '/api/admin/reload', json={}, timeout=30)
        caller.join(30)
        assert reloaded.status_code == 200 and not caller.is_alive()
        assert len(statuses) == 40 and set(statuses) == {200}
        assert api.get(url + '/health', timeout=5).json()['model_version'] == 'v1.1'
        after = api.get(url + '/api/recommend', params={'user_id': 'unknown'}, timeout=10)
        assert after.status_code == 200 and len(after.json()['recommendations']) == 10
        # Unchanged measured candidate is rejected, demonstrating no forced promotion.
        shutil.copytree(root / 'v1.1', root / 'v1.2')
        candidate = registry.record('v1.1')
        registry.register('v1.2', candidate['config'], Path(candidate['data_path']),
                          promoted['comparison']['candidate'], 'v1.1', journal.high_watermark())
        equal = copy.deepcopy(promoted['comparison']); equal['baseline'] = equal['candidate']
        assert not registry.decide('v1.2', equal, spec)
        assert registry.read()['active'] == 'v1.1'
        registry.rollback('v1.1', 'v1.0', 'controlled rollback drill after measured promotion')
        rollback = api.post(url + '/api/admin/reload', json={}, timeout=30)
        assert rollback.status_code == 200 and api.get(url + '/health', timeout=5).json()['model_version'] == 'v1.0'
        # Corrupt a registered non-active copy; preload failure must preserve service availability.
        old = app.state.recommend
        (root / 'v1.2/ranking/deepfm.pt').write_bytes(b'controlled-corruption')
        try:
            registry.verify('v1.2')
            raise AssertionError('corrupt bundle was accepted')
        except ValueError:
            pass
        assert app.state.recommend is old
        assert api.get(url + '/api/recommend', params={'user_id': 'unknown'}, timeout=10).status_code == 200
        waiting = trigger(cfg, lambda *args: None)
        assert waiting['status'] == 'WAITING'
        log_source = output.parent / 'experiments/C/ct_fixture_log.jsonl'
        log_source.parent.mkdir(parents=True, exist_ok=True)
        # Publish only aggregated lifecycle evidence, never raw journals/data/models.
        with log_source.open('w', encoding='utf-8') as stream:
            for line in registry.log.read_text().splitlines():
                stream.write(json.dumps(dict(json.loads(line), scope='controlled_fixture', fixture_run=work.name), ensure_ascii=False, allow_nan=False) + '\n')
        with (output.parent / 'ct_log.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(log_source.read_text())
        training_sources = {}
        training_results = Path(registry.record('v1.1')['data_path']).parent / 'results'
        for key, name in [('candidate', 'candidate_training_dev.json'), ('ranking', 'ranking_training_dev.json'), ('session', 'session_training_dev.json')]:
            destination = log_source.parent / f'ct_training_{key}_fixture.json'
            shutil.copy2(training_results / name, destination)
            training_sources[key] = dict(source=str(destination), sha256=file_hash(destination))
        from src.evaluation.reporting import environment
        env = environment()
        env['benchmark_scope'] = 'native controlled CT training and HTTP reload; memory FeatureStore; Docker info is descriptive only'
        report = dict(environment=env, status='PASS', acceptance='UNMEASURED', scale='controlled_fixture', seed=42,
                      scope='400 items/24 users/6000 source events; 5000 initial; additional observed view/cart/purchase only; '
                            'initial ranker deliberately constant; real candidate training and measured paired valid improvement; '
                            'not production dev/full quality or Docker reproduction',
                      source_fingerprint=source_manifest['generation_fingerprint'], source_counts=source_manifest['counts'],
                      new_events=accepted, threshold=spec['retrain_log_threshold'],
                      default_threshold=load_config()['ct']['retrain_log_threshold'],
                      monitor=alert, concurrent_trigger=busy, training=promoted,
                      checks=dict(alert=True, threshold=True, duplicate_trigger_blocked=True,
                                  real_three_model_retraining=True, fresh_chronological_split=True,
                                  increment=True, paired_valid_improvement=True, no_improvement_retained=True,
                                  atomic_http_reload=True, rollback=True, corrupt_bundle_rejected=True,
                                  new_events_consumed_once=True),
                      api=dict(before=before.status_code, after=after.status_code,
                               reloaded=reloaded.json(), rollback=rollback.json(),
                               concurrent_requests=len(statuses), all_concurrent_http_200=all(s == 200 for s in statuses)),
                      versions={name: dict(status=record['status'], parent=record['parent'], hashes=record['hashes'])
                                for name, record in registry.read()['versions'].items()},
                      artifacts=dict(registry=str(registry.path), registry_sha256=file_hash(registry.path),
                                     log=str(log_source), log_sha256=file_hash(log_source), training=training_sources),
                      full_test_quality='UNMEASURED', docker_reproduction='UNMEASURED')
        write_json(output, report)
        return report
    finally:
        api.close(); server.should_exit = True; thread.join(10); sock.close()


def verify_existing(output: Path) -> None:
    from src.ct.model_registry import ModelRegistry
    report = json.loads(output.read_text())
    assert report['status'] == 'PASS' and report['acceptance'] == 'UNMEASURED'
    assert report['scale'] == 'controlled_fixture' and report['seed'] == 42
    assert all(report['checks'].values()) and report['new_events'] >= report['threshold']
    comparison = report['training']['comparison']
    assert comparison['split'] == 'valid'
    assert comparison['baseline']['validation_fingerprint'] == comparison['candidate']['validation_fingerprint'] == comparison['validation_fingerprint']
    assert comparison['candidate']['ctr_auc'] > comparison['baseline']['ctr_auc'] + .001
    assert comparison['candidate']['ctr_auc'] >= .7
    artifacts = report['artifacts']
    assert file_hash(Path(artifacts['registry'])) == artifacts['registry_sha256']
    assert file_hash(Path(artifacts['log'])) == artifacts['log_sha256']
    events = [json.loads(line) for line in Path(artifacts['log']).read_text().splitlines()]
    assert {'registered', 'initialized', 'monitor', 'training_started', 'promoted', 'retained', 'rollback', 'reloaded'} <= {row['event'] for row in events}
    assert all(row['scope'] == 'controlled_fixture' for row in events)
    for key, item in artifacts['training'].items():
        assert file_hash(Path(item['source'])) == item['sha256'] == comparison['training_reports'][key]
        training = json.loads(Path(item['source']).read_text())
        assert training['status'] == 'PASS' and training['checkpoint_reload'] == 'PASS'
    registry = ModelRegistry(Path(artifacts['registry']).parent, Path(artifacts['log']))
    for version in ('v1.0', 'v1.1'):
        assert registry.verify(version)['hashes'] == report['versions'][version]['hashes']
    assert registry.read()['active'] == 'v1.0'
    assert report['api']['concurrent_requests'] == 40 and report['api']['all_concurrent_http_200']


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-dir', type=Path)
    parser.add_argument('--verify-existing', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('docs/results/ct_dev_fixture.json'))
    args = parser.parse_args()
    if args.verify_existing:
        verify_existing(args.output)
        print('Existing CT evidence and local registered bundles: PASS')
        return 0
    work = args.work_dir or Path('models/.ct/verification') / uuid.uuid4().hex[:10]
    report = verify(work.resolve(), args.output)
    verify_existing(args.output)
    print(json.dumps(dict(status=report['status'], new_events=report['new_events'],
                          comparison=report['training']['comparison'], output=str(args.output)), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
