"""Terminal summaries must retain real outcomes and durable stream semantics."""
import json

import pytest

from scripts.demo import summarize_ab
from src.ct.storage import Journal


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
