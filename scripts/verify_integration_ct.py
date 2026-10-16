"""Full-data CT: real HTTP observations, actual trainers, guarded reload/rollback."""
from __future__ import annotations

import argparse
import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import requests
from src.common.artifacts import file_hash, write_json
from src.common.config import load_config
from src.ct.monitor import monitor
from src.ct.retrain_trigger import build_from_journal, components, reload_api, trigger
from src.ct.storage import file_lock


def verify(url: str, output: Path) -> dict:
    cfg = load_config()
    if cfg['scale'] != 'full':
        raise ValueError('this runner requires the full dataset')
    spec, journal, registry = components(cfg)
    assert spec['retrain_log_threshold'] == cfg['ct']['retrain_log_threshold']
    assert registry.read()['active'] == 'v1.0', 'run on a separate initial full verification deployment'
    run_id = 'ct-integration-' + uuid.uuid4().hex
    isolated = copy.deepcopy(cfg)
    isolated['paths']['model_dir'] = str(registry.root / '.ct' / run_id)
    waiting = trigger(isolated, lambda *args: (_ for _ in ()).throw(AssertionError('premature training')))
    assert waiting['status'] == 'WAITING' and waiting['new_events'] == 0
    with file_lock(registry.root / '.ct' / 'training.lock'):
        busy = trigger(cfg, lambda *args: (_ for _ in ()).throw(AssertionError('duplicate training')))
        assert busy['status'] == 'BUSY'
    threshold = int(spec['retrain_log_threshold'])
    per_request = 50
    count = (threshold + per_request - 1) // per_request
    assert count <= cfg['scales']['full']['n_users']
    start_watermark = journal.high_watermark()
    def observe(index: int) -> int:
        uid = f'U{index + 1:06d}'
        with requests.Session() as client:
            client.trust_env = False
            response = client.get(url + '/api/recommend', params={'user_id': uid, 'top_n': str(per_request)}, timeout=120)
            response.raise_for_status()
            rows = response.json()['recommendations']
            assert len(rows) == per_request
            headers = {'X-Recommendation-Request-ID': response.headers['X-Recommendation-Request-ID']}
            applied = 0
            for position, item in enumerate(rows):
                if index * per_request + position >= threshold:
                    break
                event = dict(event_id=f'{run_id}-{index}-{position}', user_id=uid,
                             product_id=item['product_id'], event_type='view', session_id=f'{run_id}-{index}')
                reply = client.post(url + '/api/event', json=event, headers=headers, timeout=120)
                reply.raise_for_status()
                assert reply.json()['applied'] is True
                applied += 1
            return applied
    print(f'CT: emitting {threshold} unique HTTP observations over {count} top50 requests', flush=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        observed = sum(pool.map(observe, range(count)))
    assert observed == threshold
    with journal.connect() as db:
        rows = db.execute('SELECT COUNT(*) FROM events WHERE id LIKE ?', (run_id + '-%',)).fetchone()[0]
    assert rows == threshold
    # This advances only the monitoring query clock. HTTP arrival timestamps and
    # training observations remain the actual server times; no hour-long wait is claimed.
    monitoring_clock = time.time() + int(spec['attribution_seconds']) + 1
    quality = monitor(journal, spec, monitoring_clock, registry.log)
    assert quality['top50_requests'] >= count and 'hitrate_below_threshold' in quality['alerts']
    write_json(output.with_name('ct_full_running.json'), dict(status='RUNNING', observed_events=observed,
        run_id=run_id, start_watermark=start_watermark, monitor=quality,
        scope='scripted view-only responses to real top50 HTTP requests; monitor maturity uses explicit advanced clock'))
    print('CT: starting actual full candidate/ranking/session retraining and paired valid evaluation', flush=True)
    result = trigger(cfg, lambda version, through, current: build_from_journal(cfg, version, through, current))
    assert result['status'] in ('PROMOTED', 'RETAINED')
    assert result['new_events'] >= threshold
    state = registry.read()
    assert state['last_success_seq'] == result['through_seq']
    again = trigger(cfg, lambda *args: (_ for _ in ()).throw(AssertionError('events consumed twice')))
    assert again['status'] == 'WAITING'
    reloads = []
    rollback = False
    if result['status'] == 'PROMOTED':
        version = result['version']
        reloads.append(reload_api(url, version))
        with requests.Session() as client:
            client.trust_env = False
            assert client.get(url + '/health', timeout=30).json()['model_version'] == version
            response = client.get(url + '/api/recommend', params={'user_id': 'U000001'}, timeout=120)
            response.raise_for_status()
        registry.rollback(version, 'v1.0', 'full integration verification; restore frozen initial deployment')
        reloads.append(reload_api(url, 'v1.0'))
        with requests.Session() as client:
            client.trust_env = False
            assert client.get(url + '/health', timeout=30).json()['model_version'] == 'v1.0'
            response = client.get(url + '/api/recommend', params={'user_id': 'U000001'}, timeout=120)
            response.raise_for_status()
        rollback = True
    else:
        assert registry.read()['active'] == 'v1.0'
    comparison = result['comparison']
    assert comparison['split'] == 'valid'
    assert comparison['baseline']['validation_fingerprint'] == comparison['candidate']['validation_fingerprint']
    manifest = json.loads((Path(cfg['paths']['data_dir']) / 'split_manifest.json').read_text())
    report = dict(status='PASS' if rollback else 'PARTIAL', scale='full', run_id=run_id,
        data_fingerprint=manifest['generation_fingerprint'], observed_new_events=observed, threshold=threshold,
        premature_trigger=waiting, concurrent_trigger=busy, monitor=quality, retraining=result,
        repeated_trigger=again, real_reload_and_rollback=rollback, reloads=reloads,
        checks={'full_three_model_retraining': True, 'threshold': True, 'event_watermark': True,
                'paired_valid': True, 'real_reload_and_rollback': rollback},
        source_hashes={str(p): file_hash(p) for p in Path('src/ct').glob('*.py')},
        scope='full original dataset plus genuinely new scripted observations; actual three trainers and paired valid selection; no test tuning',
        limitations=['view-only responses are a functional CT scenario, not measured production CTR or lift',
                     'monitor attribution maturity uses an explicit advanced query clock; real event timestamps are preserved',
                     'a retained model is reported honestly and does not establish a new full rollback'])
    write_json(output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-url', default='http://127.0.0.1:8000')
    parser.add_argument('--output', type=Path, default=Path('docs/results/integration/ct_full.json'))
    args = parser.parse_args()
    report = verify(args.api_url.rstrip('/'), args.output)
    print(f"Full CT {report['status']}: {args.output}", flush=True)
    return 0 if report['status'] == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
