"""Terminal summaries must retain real outcomes and durable stream semantics."""
import json

import pytest

from scripts.demo import summarize_ab
from src.ct.storage import Journal


def test_pdf_examples_uses_live_clicks_and_separate_experiment_processes(tmp_path, monkeypatch):
    from scripts import demo
    calls, children = [], []
    def request(url, payload=None):
        calls.append((url, payload))
        if url.endswith('/api/search'):
            return dict(search_type='text', results=[dict(product_id=p, name='검정 후드티', score=.7, price=59000)
                for p in ('actual-1','actual-2')], total_count=50000, latency_ms=42.)
        if url.endswith('/api/event'):
            return dict(applied=True)
        clicks = [body for endpoint, body in calls if endpoint.endswith('/api/event')]
        return dict(user_id=clicks[0]['user_id'], recommendations=[], pipeline_latency={},
                    session_context=dict(recent_clicks=[p['product_id'] for p in clicks], session_interest='hoodie'))
    monkeypatch.setattr(demo, 'request', request)
    monkeypatch.setattr(demo.subprocess, 'call', lambda args: children.append(args) or 0)
    output = tmp_path / 'examples'
    assert demo.examples(['--api-url','http://api','--output-dir',str(output)]) == 0
    assert len(children) == 2 and '5000' in children[0] and '30' in children[0]
    assert children[1][2:4] == ['ct','--drill']
    actual = json.loads((output / 'recommendation.json').read_text())
    assert actual['session_context']['recent_clicks'] == ['actual-1','actual-2']
    assert json.loads((output / 'search.json').read_text())['total_count'] == 50000
    with pytest.raises(FileExistsError):
        demo.examples(['--output-dir',str(output)])


def test_ab_serializes_with_ct_and_releases_lock_on_failure(tmp_path, monkeypatch):
    from scripts.demo import operational
    from src.ct.storage import file_lock
    from src.common.config import load_config
    cfg = load_config()
    cfg['paths'].update(model_dir=str(tmp_path / 'models'), results_dir=str(tmp_path / 'results'))
    lock = tmp_path / 'models' / '.ct' / 'training.lock'
    monkeypatch.setattr('docker.runtime.runtime_config', lambda: cfg)
    def fail(cfg, output):
        with pytest.raises(BlockingIOError), file_lock(lock, blocking=False):
            pass
        raise RuntimeError('original experiment failure')
    monkeypatch.setattr('src.evaluation.ab_test.run', fail)
    with pytest.raises(RuntimeError, match='original experiment failure'):
        operational(['ab'])
    with file_lock(lock, blocking=False):
        pass


def test_ct_batch_is_atomic_idempotent_and_keeps_attribution_checks(tmp_path):
    journal = Journal(tmp_path / 'journal.sqlite3')
    payload = dict(event_id='e1', user_id='u', product_id='p', event_type='view')
    journal.exposure('r', 'u', ['p'], 10, 'v1', 10)
    rows = [(payload, 11), (dict(payload, event_id='e2', event_type='purchase'), 12)]
    assert journal.events(rows, 'r', 20) == 2
    assert journal.events(rows, 'r', 20) == 0
    assert journal.count_since(0) == 2
    with pytest.raises(ValueError, match='unsupported'):
        journal.events([(dict(payload, event_id='e3'), 13),
                        (dict(payload, event_id='e4', event_type='search'), 14)])
    assert journal.count_since(0) == 2
    with pytest.raises(ValueError, match='unattributable'):
        journal.events([(dict(payload, event_id='e5', user_id='other'), 12)], 'r')
    assert journal.count_since(0) == 2


def test_ab_terminal_preserves_negative_lift_and_undefined_inference(capsys):
    from pathlib import Path
    report = json.loads(Path('docs/results/integration/20261107_requirements/ab_demo.json').read_text())
    summarize_ab(report)
    text = capsys.readouterr().out
    assert '100명' in text and '7일' in text and '-23.60%' in text
    assert '유의하지 않음' in text and '%p' in text and 'MAB Exploration' in text
    report['inference']['cvr'].update(control=None, treatment=None, relative_lift=None,
                                    difference_ci95=None, z_p_value=None)
    summarize_ab(report)
    assert '미측정/추론 불가' in capsys.readouterr().out


def test_ct_human_monitor_does_not_invent_missing_measurements(tmp_path, monkeypatch, capsys):
    from src.common.config import load_config
    from src.ct.monitor import monitor
    from src.ct.retrain_trigger import settings
    monkeypatch.setenv('CT_OUTPUT', 'human')
    journal = Journal(tmp_path / 'journal.sqlite3')
    result = monitor(journal, settings(load_config()), 100, tmp_path / 'ct.jsonl')
    assert result['status'] == 'UNMEASURED'
    assert '미측정' in capsys.readouterr().err
    assert json.loads((tmp_path / 'ct.jsonl').read_text())['hit_rate_at_50'] is None


def test_ct_default_output_does_not_truncate_another_monitor(tmp_path, monkeypatch):
    import io
    from types import SimpleNamespace
    from src.common.config import load_config
    from scripts import demo
    cfg = load_config()
    cfg['paths'].update(model_dir=str(tmp_path / 'models'), results_dir=str(tmp_path / 'results'))
    monkeypatch.setattr('docker.runtime.runtime_config', lambda: cfg)
    counter = iter((1, 2))
    def process(*args, **kwargs):
        stream = io.BytesIO((json.dumps(dict(sequence=next(counter))) + '\n').encode())
        return SimpleNamespace(stdout=stream, wait=lambda: 0, poll=lambda: 0)
    monkeypatch.setattr(demo.subprocess, 'Popen', process)
    assert demo.operational(['ct']) == demo.operational(['ct']) == 0
    paths = list((tmp_path / 'results/ct-cli').glob('*.jsonl'))
    assert len(paths) == 2
    assert sorted(json.loads(p.read_text())['sequence'] for p in paths) == [1, 2]


def test_ct_watch_flushes_output_before_process_exit(tmp_path):
    import os
    import signal
    import subprocess
    import sys
    import time
    import yaml
    from src.common.config import load_config
    cfg = load_config()
    cfg['paths'].update(model_dir=str(tmp_path / 'models'), results_dir=str(tmp_path / 'results'), by_scale={})
    cfg['serving']['ct']['poll_seconds'] = .1
    config = tmp_path / 'config.yaml'
    config.write_text(yaml.safe_dump(cfg), encoding='utf-8')
    output = tmp_path / 'watch.jsonl'
    process = subprocess.Popen([sys.executable, 'scripts/demo.py', 'ct', '--watch', '--json',
                                '--output', str(output)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env={**os.environ, 'CONFIG_PATH': str(config), 'RUNTIME_RESULTS_DIR': str(tmp_path / 'results')})
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and (not output.exists() or not output.stat().st_size):
            if process.poll() is not None:
                pytest.fail(process.communicate()[1].decode())
            time.sleep(.05)
        assert process.poll() is None
        assert json.loads(output.read_text().splitlines()[0])['status'] == 'UNMEASURED'
    finally:
        process.send_signal(signal.SIGINT)
        process.communicate(timeout=10)
