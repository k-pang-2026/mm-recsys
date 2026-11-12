"""Serialized log/degradation triggers; failures preserve pending events and active models."""
from __future__ import annotations

from typing import Any

import argparse
import copy
import json
import math
from pathlib import Path
import time
import requests
import traceback

from src.common.console import log, emit_json, run_cli
from src.common.artifacts import write_json, fingerprint
from src.common.config import load_config
from src.ct.model_registry import ModelRegistry
from src.ct.storage import Journal, append_log, file_lock


def settings(cfg: dict) -> dict:
    spec = copy.deepcopy(cfg['serving']['ct'])
    spec.setdefault('hitrate_threshold', cfg['ct']['hitrate_threshold'])
    spec.setdefault('retrain_log_threshold', cfg['ct']['retrain_log_threshold'])
    spec.setdefault('retry_seconds', spec['poll_seconds'])
    spec.setdefault('retrain_on_degradation', True)
    if not isinstance(spec['retrain_on_degradation'], bool):
        raise ValueError('CT retrain_on_degradation must be boolean')
    for key in ('poll_seconds', 'retry_seconds', 'recent_seconds', 'attribution_seconds', 'min_mature_requests', 'retrain_log_threshold'):
        if not math.isfinite(float(spec[key])) or float(spec[key]) <= 0:
            raise ValueError(f'CT {key} must be positive')
    return spec


def components(cfg: dict) -> tuple[dict, Journal, ModelRegistry]:
    spec = settings(cfg)
    return (spec, Journal(Path(cfg['paths']['model_dir']) / '.ct' / 'journal.sqlite3'),
            ModelRegistry(Path(cfg['paths']['model_dir']), Path(cfg['paths']['results_dir']) / 'ct_log.jsonl'))


def trigger(cfg: dict, build: Any, *, monitoring: dict | None = None) -> dict:
    from src.ct.monitor import measure
    spec, journal, registry = components(cfg)
    try:
        with file_lock(registry.root / '.ct' / 'training.lock', blocking=False):
            state = registry.read(); through = journal.high_watermark()
            count = journal.count_since(state['last_success_seq'], through)
            now = time.time()
            if monitoring is None or monitoring.get('model_version') != state['active']:
                monitoring = measure(journal, spec, now, state['active'])
            degraded = bool(state['active'] and spec['retrain_on_degradation'] and monitoring['alerts'])
            threshold = int(spec['retrain_log_threshold'])
            if count < threshold and not degraded:
                return dict(status='WAITING', new_events=count, threshold=spec['retrain_log_threshold'])
            if not state['active']:
                raise ValueError('register and initialize v1.0 before retraining')
            reason = 'new_logs' if count >= threshold else 'performance_degradation'
            with journal.connect() as db:
                requests_count = db.execute('SELECT COUNT(*) FROM requests').fetchone()[0]
            observed = [state['active'], through, requests_count, fingerprint(cfg)]
            attempt_path = registry.root / '.ct' / 'last_attempt.json'
            previous = json.loads(attempt_path.read_text()) if attempt_path.exists() else None
            if previous and previous['input'][0] == state['active']:
                pending = previous['result']['status'] == 'WAITING_FOR_LABELS'
                unchanged = previous['input'] == observed
                retry_after = max(0., float(spec['retry_seconds']) - (now - previous['at']))
                if unchanged or (retry_after and (pending or reason == 'performance_degradation')):
                    result = dict(previous['result']) if pending else dict(status='WAITING')
                    result.update(new_events=count, threshold=threshold, retry_after_seconds=retry_after,
                                  reason='unchanged_observations' if unchanged else 'retry_cooldown')
                    log('CT', '학습 대기', '입력 변화·재시도 간격을 확인해 스냅샷을 다시 생성하지 않습니다.')
                    return result
            parent, version = state['active'], registry.next_version()
            append_log(registry.log, dict(event='training_started', parent=parent, version=version,
                                          new_events=count, through_seq=through, trigger_reason=reason,
                                          alerts=monitoring['alerts']))
            try:
                # build must only include journal events through this captured watermark.
                result = build(version, through, registry)
                if result.get('status') == 'WAITING_FOR_LABELS':
                    append_log(registry.log, dict(event='training_deferred', new_events=count,
                                                 through_seq=through, **result))
                    result = dict(new_events=count, through_seq=through, trigger_reason=reason, **result)
                else:
                    registry.register(version, result['config'], Path(result['data_path']),
                                      result['comparison']['candidate'], parent, through)
                    promoted = registry.decide(version, result['comparison'], spec)
                    result = dict(status='PROMOTED' if promoted else 'RETAINED', version=version,
                                  active=registry.read()['active'], new_events=count, through_seq=through,
                                  trigger_reason=reason, comparison=result['comparison'])
                write_json(attempt_path, dict(input=observed, at=time.time(), result=result))
                return result
            except Exception as error:
                append_log(registry.log, dict(event='training_failed', version=version,
                                              error=f'{type(error).__name__}: {error}'))
                raise
    except BlockingIOError:
        return dict(status='BUSY')


def build_from_journal(cfg: dict, version: str, through: int, registry: ModelRegistry) -> dict:
    import gc
    import pandas as pd
    from src.ct.training import train_all, validation
    from src.ct.snapshot import snapshot, journal_tables, training_eligibility
    from src.serving.model_loader import load_record
    from src.serving.memory_store import MemoryFeatureStore
    from src.common.artifacts import file_hash
    spec, journal, _ = components(cfg)
    parent = registry.record(registry.read()['active'])
    source = Path(parent['data_path'])
    log('CT', '스냅샷', '관측 로그를 묶음 단위로 읽고 시간순 학습 스냅샷을 생성합니다.')
    events, impressions = journal_tables(source, journal, parent['trained_through_seq'], through)
    # A failed attempt is kept for diagnosis; select a fresh unique workspace on retry.
    import uuid
    work = registry.root / '.ct' / 'runs' / f'{version}-{uuid.uuid4().hex[:8]}'
    data_path = work / 'data'
    manifest = snapshot(source, data_path, events, impressions, cfg)
    local = copy.deepcopy(cfg); local['paths']['data_dir'] = str(data_path)
    local['simulator']['reference_time'] = (pd.Timestamp(manifest['observed_through']) + pd.Timedelta(microseconds=1)).isoformat()
    # Trainers load the immutable snapshot themselves; retaining these copies exhausts full CT memory.
    del events, impressions
    gc.collect()
    eligibility = training_eligibility(data_path, local)
    write_json(work / 'eligibility.json', eligibility)
    if not eligibility['ready']:
        return dict(status='WAITING_FOR_LABELS', eligibility=eligibility, data_path=str(data_path))
    log('CT', '학습 준비', '스냅샷·관측 라벨 검사 통과; 세 모델 학습을 시작합니다.')
    reports, bundle = train_all(local, work)
    gc.collect()
    bundle.rename(registry.root / version)
    # Temporary standalone registry uses the same production loaders before registration.
    staged = ModelRegistry(work / 'probe', work / 'probe.jsonl')
    staged.root.mkdir(parents=True)
    (staged.root / version).symlink_to(registry.root / version, target_is_directory=True)
    staged.register(version, local, data_path, {}, None, through)
    baseline = validation(load_record(registry, parent['version'], MemoryFeatureStore(),
                                     scoring=local['recommend'].get('scoring')), local)
    gc.collect()
    candidate = validation(load_record(staged, version, MemoryFeatureStore(),
                                      scoring=local['recommend'].get('scoring')), local)
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
        health = session.get(url.rstrip('/') + '/health', timeout=10, allow_redirects=False)
        if health.status_code != 200:
            raise RuntimeError(f'API health unavailable: HTTP {health.status_code}')
        if health.json().get('model_version') == version:
            return dict(status='unchanged', version=version)
        response = session.post(url.rstrip('/') + '/api/admin/reload', json=dict(version=version),
                                timeout=60, allow_redirects=False)
    if response.status_code != 200:
        raise RuntimeError(f'active registry changed but API reload failed: HTTP {response.status_code}; retry reload')
    return response.json()


def main() -> int:
    parser = argparse.ArgumentParser(description='CT 모니터링 및 명시적으로 활성화하는 재학습 실행기')
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--rollback', metavar='VERSION')
    parser.add_argument('--reason', default='explicit operator rollback', help='롤백 사유')
    parser.add_argument('--reload-url', help='승격·롤백 후 교체할 로컬 루프백 API URL')
    parser.add_argument('--train', action='store_true', help='신규 로그 임계치 또는 성능 저하를 감지하면 재학습')
    args = parser.parse_args(); cfg = load_config()
    from src.ct.monitor import monitor
    spec, journal, registry = components(cfg)
    if args.rollback:
        if args.watch or args.train:
            parser.error('--rollback은 --watch 또는 --train과 함께 사용할 수 없습니다.')
        state = registry.read()
        registry.rollback(state['active'], args.rollback, args.reason)
        if args.reload_url:
            reload_api(args.reload_url, args.rollback)
        emit_json(dict(status='ROLLED_BACK', active=registry.read()['active']))
        return 0
    log('CT', '시작', f"모니터링 주기={spec['poll_seconds']}초 / 재학습 임계치={spec['retrain_log_threshold']}건 / 재학습 활성={args.train} / 활성 모델={registry.read()['active']}")
    while True:
        if args.train and args.reload_url and registry.read()['active']:
            try:
                reload_api(args.reload_url, registry.read()['active'])
            except (requests.RequestException, RuntimeError) as error:
                if not args.watch:
                    raise
                append_log(registry.log, dict(event='reload_retry', error=str(error)))
                traceback.print_exc()
                time.sleep(float(spec['poll_seconds']))
                continue
        measured = monitor(journal, spec, time.time(), registry.log, registry.read()['active'])
        if args.train:
            result = trigger(cfg, lambda version, through, reg: build_from_journal(cfg, version, through, reg), monitoring=measured)
            if result['status'] == 'WAITING':
                log('CT', '대기', f"신규 로그={result['new_events']:,}건 / 임계치={result['threshold']:,}건", status='대기')
            elif result['status'] == 'BUSY':
                log('CT', '대기', '다른 재학습이 실행 중입니다. 다음 주기에 다시 확인합니다.', status='대기')
            emit_json(result, jsonl=args.watch)
            if result['status'] == 'PROMOTED' and args.reload_url:
                if args.watch:
                    continue  # Synchronize the registry active version before any further training.
                reload_api(args.reload_url, result['active'])
        else:
            state = registry.read()
            log('CT', '누적 로그', f"신규 로그={journal.count_since(state['last_success_seq']):,}건 / 임계치={spec['retrain_log_threshold']:,}건 / 모니터링만 수행", status='확인')
            emit_json(measured, jsonl=args.watch)
        if not args.watch:
            break
        time.sleep(float(spec['poll_seconds']))
    return 0


if __name__ == '__main__':
    raise SystemExit(run_cli(main, 'CT', 'registry·학습 입력·API 상태와 원본 오류를 확인하세요. 기존 모델과 이벤트를 보존한 채 재시도하세요.'))
