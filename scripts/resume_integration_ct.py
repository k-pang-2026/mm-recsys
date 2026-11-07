"""Resume only interrupted paired validation of verified, already trained full CT artifacts."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.common.artifacts import file_hash, write_json
from src.common.console import emit_json, log, run_cli
from src.common.config import load_config
from src.ct.model_registry import ModelRegistry
from src.ct.retrain_trigger import components, trigger, reload_api
from src.ct.storage import file_lock, append_log
from src.ct.training import validation
from src.serving.memory_store import MemoryFeatureStore
from src.serving.model_loader import load_record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path('docs/results/integration'))
    parser.add_argument('--observed-journal', action='store_true', help='실제 관측 로그의 ct_before_stdout.json을 기준으로 중단된 검증을 재개')
    args = parser.parse_args()
    cfg = load_config()
    spec, journal, registry = components(cfg)
    out = args.output_dir
    running = json.loads((out / ('ct_before_stdout.json' if args.observed_journal else 'ct_full_running.json')).read_text())
    assert cfg['scale'] == 'full'
    if args.observed_journal:
        assert running['new_events'] >= running['threshold'] == spec['retrain_log_threshold']
    else:
        assert running['observed_events'] == spec['retrain_log_threshold']
    events = [json.loads(line) for line in registry.log.read_text().splitlines()]
    started = [row for row in events if row['event'] == 'training_started'][-1]
    version, parent, through = started['version'], started['parent'], started['through_seq']
    assert registry.read()['active'] == parent
    assert parent == (running['registry']['active'] if args.observed_journal else 'v1.0')
    assert version not in registry.read()['versions']
    works = list((registry.root / '.ct/runs').glob(version + '-*'))
    assert len(works) == 1
    work = works[0]
    staged = ModelRegistry(work / 'probe', work / 'probe.jsonl')
    record = staged.verify(version)
    local = record['config']
    assert record['trained_through_seq'] == through
    manifest = json.loads((Path(record['data_path']) / 'split_manifest.json').read_text())
    original = json.loads((Path(registry.record(parent)['data_path']) / 'split_manifest.json').read_text())
    assert manifest['parent_fingerprint'] == original['generation_fingerprint']
    assert manifest['counts']['products'] == 50000 and manifest['counts']['users'] == 10000
    for name, sha in manifest['file_hashes'].items():
        assert file_hash(Path(record['data_path']) / name) == sha
    reports = {kind: work / 'results' / f'{kind}_training_full.json' for kind in ('candidate', 'ranking', 'session')}
    assert all(path.exists() for path in reports.values())
    for path in reports.values():
        report = json.loads(path.read_text())
        assert report.get('scale') == 'full' and report['status'] == report['checkpoint_reload'] == 'PASS'
    if args.observed_journal:
        assert through == running['high_watermark'] and registry.read()['last_success_seq'] == running['registry']['last_success_seq']
        observed = journal.count_since(running['registry']['last_success_seq'], through)
        assert observed == running['new_events'] == started['new_events']
        assert journal.count_since(through) < spec['retrain_log_threshold'], 'pause bulk replay before recovery'
    else:
        with journal.connect() as db:
            observed = db.execute('SELECT COUNT(*) FROM events WHERE id LIKE ?', (running['run_id'] + '-%',)).fetchone()[0]
        assert observed == running['observed_events']
        assert journal.high_watermark() == through, 'replay must remain paused'
    recovery = dict(status='RUNNING', scale='full', version=version, captured_watermark=through,
        scope='resume interrupted comparison only; retain original full training, captured observations and immutable staged bundle',
        observed_journal=args.observed_journal,
        training_reports={kind: file_hash(path) for kind, path in reports.items()},
        hashes=record['hashes'], source_hashes={str(p):file_hash(p) for p in Path('src/ct').glob('*.py')})
    write_json(out / 'ct_recovery_full.json', recovery)
    with file_lock(registry.root / '.ct/training.lock', blocking=False):
        assert registry.read()['active'] == parent and version not in registry.read()['versions']
        if args.observed_journal:
            assert registry.read()['last_success_seq'] == running['registry']['last_success_seq']
        append_log(registry.log, dict(event='validation_resumed', version=version, through_seq=through,
                                     reason='original verification process interrupted after all three full trainers completed'))
        values = {}
        for side, source, selected in [('baseline', registry, parent), ('candidate', staged, version)]:
            log('CT 복구', 'valid 평가', f'비교 대상={side} / 규모=full / 모델={selected}')
            start = time.perf_counter()
            service = load_record(source, selected, MemoryFeatureStore())
            values[side] = validation(service, local)
            del service
            import gc
            gc.collect()
            write_json(out / f'ct_{side}_valid_full.json', dict(status='PASS', scale='full',
                seconds=time.perf_counter()-start, metrics=values[side], bundle_hashes=source.verify(selected)['hashes']))
        assert values['baseline']['validation_fingerprint'] == values['candidate']['validation_fingerprint']
        comparison = dict(split='valid', validation_fingerprint=values['candidate']['validation_fingerprint'],
                          **values, training_reports=recovery['training_reports'])
        write_json(work / 'comparison.json', comparison)
        registry.register(version, local, Path(record['data_path']), values['candidate'], parent, through)
        promoted = registry.decide(version, comparison, spec)
    result = dict(status='PROMOTED' if promoted else 'RETAINED', version=version,
                  active=registry.read()['active'], new_events=started['new_events'], through_seq=through,
                  comparison=comparison)
    again = trigger(cfg, lambda *args: (_ for _ in ()).throw(AssertionError('consumed twice')))
    assert again['status'] == 'WAITING' and registry.read()['last_success_seq'] == through
    reloads=[]
    if promoted:
        reloads.append(reload_api('http://127.0.0.1:8000', version))
        import requests
        with requests.Session() as client:
            client.trust_env=False
            assert client.get('http://127.0.0.1:8000/health',timeout=30).json()['model_version']==version
            client.get('http://127.0.0.1:8000/api/recommend',params={'user_id':'U000001'},timeout=120).raise_for_status()
        if not args.observed_journal:
            registry.rollback(version,parent,'full integration verification; restore frozen initial deployment')
            reloads.append(reload_api('http://127.0.0.1:8000',parent))
            with requests.Session() as client:
                client.trust_env=False
                assert client.get('http://127.0.0.1:8000/health',timeout=30).json()['model_version']==parent
                client.get('http://127.0.0.1:8000/api/recommend',params={'user_id':'U000001'},timeout=120).raise_for_status()
    if args.observed_journal:
        recovery.update(status='PASS', repeated_trigger=again, reloads=reloads)
        write_json(out / 'ct_recovery_full.json', recovery)
        result['recovery'] = dict(source=str(out / 'ct_recovery_full.json'), sha256=file_hash(out / 'ct_recovery_full.json'))
        write_json(out / 'ct_natural.json', result)
        log('CT 복구', '결과', f"판정={result['status']} / 신규 로그={observed:,}건 / 활성 모델={registry.read()['active']}", status='완료')
        emit_json(result)
        return 0
    report=dict(status='PASS' if promoted else 'PARTIAL',scale='full',run_id=running['run_id'],
        data_fingerprint=original['generation_fingerprint'],observed_new_events=observed,threshold=spec['retrain_log_threshold'],
        monitor=running['monitor'], retraining=result,repeated_trigger=again,real_reload_and_rollback=promoted,reloads=reloads,
        checks=dict(full_three_model_retraining=True,threshold=True,event_watermark=True,paired_valid=True,real_reload_and_rollback=promoted),
        source_hashes=recovery['source_hashes'],recovery=dict(source=str(out/'ct_recovery_full.json')),
        scope='actual full trainers and same paired valid selection; interrupted comparison resumed with verified staged artifacts',
        limitations=['scripted view-only functional scenario, not production lift','monitor maturity uses explicit advanced query clock',
                     'retention never establishes promotion/rollback','original test quality was previously observed; CT selection uses valid only'])
    recovery['status']='PASS';write_json(out/'ct_recovery_full.json',recovery)
    report['recovery']['sha256']=file_hash(out/'ct_recovery_full.json')
    write_json(out/'ct_full.json',report)
    log('CT 복구', '결과', f"판정={report['status']} / 신규 로그={observed:,}건 / 활성 모델={registry.read()['active']}",
        status='완료' if promoted else '기존 모델 유지')
    emit_json(report)
    return 0 if promoted else 2

if __name__=='__main__':
    raise SystemExit(run_cli(main, 'CT 복구', '중단된 학습의 원본 근거·번들 해시·로그 watermark와 API 연결을 확인하세요.'))
