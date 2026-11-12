"""The compact CT path must retain every observation and the temporal contract."""
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pytest
from src.ct.snapshot import first_by_id, journal_tables, snapshot, training_eligibility
from src.ct.storage import Journal
from src.recommendation.testing import service_fixture
from src.simulator.split import chronological_split


def test_journal_closes_connections_and_rolls_back_failed_transactions(tmp_path):
    import sqlite3
    journal=Journal(tmp_path/'journal.db')
    with journal.connect() as db:
        db.execute('CREATE TABLE probe (value INTEGER)')
    with pytest.raises(sqlite3.ProgrammingError,match='closed'):
        db.execute('SELECT 1')
    with pytest.raises(RuntimeError,match='abort'):
        with journal.connect() as failed:
            failed.execute('INSERT INTO probe VALUES (1)')
            raise RuntimeError('abort')
    with pytest.raises(sqlite3.ProgrammingError,match='closed'):
        failed.execute('SELECT 1')
    with journal.connect() as check:
        assert check.execute('SELECT COUNT(*) FROM probe').fetchone()[0]==0


def test_journal_batches_preserve_rows_and_snapshot_split_contract(tmp_path):
    cfg, data = service_fixture(tmp_path)
    source = Path(cfg['paths']['data_dir'])
    original = pd.concat([data['train'], data['valid']], ignore_index=True)
    original['query'] = None; original['position'] = float('nan')
    original['impression_id'] = original.impression_id.astype('string')
    original.to_parquet(source / 'events.parquet', index=False)
    at = original.timestamp.max()
    impressions = pd.DataFrame(dict(impression_id=['r:p00'], request_id=['r'], user_id=['u'],
        product_id=['p00'], exposed_at=[at], position=[1]))
    impressions.to_parquet(source / 'impressions.parquet', index=False)
    journal = Journal(tmp_path / 'journal.db')
    journal.exposure('r', 'u', ['p00'], 1, 'v1.0', at.timestamp())
    entries = [(dict(event_id=f'new-{i:05d}', user_id='u', product_id='p00', event_type='view', session_id='s'),
                at.timestamp() + 1 + i // 3) for i in range(10005)]
    assert journal.events(entries) == len(entries)
    through = journal.high_watermark()
    journal.event(dict(entries[0][0], event_id='later'), at.timestamp() + 99999)
    events, exposures = journal_tables(source, journal, 0, through)
    assert len(events) == len(original) + len(entries)
    assert 'later' not in events['event_id'].to_pylist()
    assert len(exposures) == 1  # The original exposure wins over a repeated request import.
    assert events['impression_id'].null_count == len(events)  # No fabricated links.
    expected = chronological_split(events.to_pandas(), cfg['split'])
    manifest = snapshot(source, tmp_path / 'snapshot', events, exposures, cfg)
    assert manifest['counts']['events'] == len(events)
    for name, frame in expected.items():
        actual = pd.read_parquet(tmp_path / 'snapshot/split' / f'{name}.parquet')
        pd.testing.assert_frame_equal(actual.reset_index(drop=True), frame.reset_index(drop=True))
    assert not training_eligibility(tmp_path / 'snapshot', cfg)['ready']
    # Consistent with old drop_duplicates(..., keep='first') semantics, including null values.
    small = pa.table({'id': ['a', 'b', 'a'], 'value': [None, 2, 3]})
    assert first_by_id(small, 'id').to_pydict() == {'id': ['a', 'b'], 'value': [None, 2]}


def test_deferred_training_never_consumes_events_or_replaces_model(tmp_path):
    from src.ct.bootstrap import bootstrap
    from src.ct.retrain_trigger import components, trigger
    cfg, _ = service_fixture(tmp_path)
    cfg['paths']['results_dir'] = str(tmp_path / 'results')
    cfg['serving']['ct']['retrain_log_threshold'] = 1
    bootstrap(cfg)
    _, journal, registry = components(cfg)
    journal.event(dict(event_id='new', user_id='u', product_id='p00', event_type='view'), 10)
    before = registry.read()
    result = trigger(cfg, lambda *args: dict(status='WAITING_FOR_LABELS', eligibility={'ready': False}, data_path='snapshot'))
    assert result['status'] == 'WAITING_FOR_LABELS'
    assert registry.read() == before
    assert journal.count_since(before['last_success_seq']) == 1


def test_watch_does_not_rebuild_an_unchanged_deferred_snapshot(tmp_path, monkeypatch, capsys):
    import sys
    from src.ct import retrain_trigger as runner
    from src.ct.bootstrap import bootstrap
    cfg, _ = service_fixture(tmp_path)
    cfg['paths']['results_dir'] = str(tmp_path / 'results')
    bootstrap(cfg)
    cfg['serving']['ct']['retrain_log_threshold'] = 1
    _, journal, _ = runner.components(cfg)
    journal.event(dict(event_id='pending', user_id='u', product_id='p00', event_type='view'), 10.)
    monkeypatch.setattr(sys, 'argv', ['ct', '--train', '--watch'])
    monkeypatch.setattr(runner, 'load_config', lambda: cfg)
    calls = []
    def deferred(*args):
        calls.append(True)
        return dict(status='WAITING_FOR_LABELS', data_path='fixture-snapshot')
    monkeypatch.setattr(runner, 'build_from_journal', deferred)
    polls = []
    def sleep(_):
        polls.append(True)
        if len(polls) == 2:
            raise KeyboardInterrupt
    monkeypatch.setattr(runner.time, 'sleep', sleep)
    with pytest.raises(KeyboardInterrupt):
        runner.main()
    assert len(calls) == 1
    assert '스냅샷을 다시 생성하지 않습니다' in capsys.readouterr().err


def test_deferred_retry_survives_restart_and_throttles_changing_input(tmp_path, monkeypatch):
    from src.ct import retrain_trigger as runner
    from src.ct.bootstrap import bootstrap
    cfg, _ = service_fixture(tmp_path)
    cfg['paths']['results_dir'] = str(tmp_path / 'results')
    cfg['serving']['ct'].update(retrain_log_threshold=1, retry_seconds=300)
    bootstrap(cfg)
    _, journal, registry = runner.components(cfg)
    before = registry.read()
    now = [1000.]
    monkeypatch.setattr(runner.time, 'time', lambda: now[0])
    calls = []
    def deferred(*args):
        calls.append(True)
        return dict(status='WAITING_FOR_LABELS', eligibility={'ready': False}, data_path='fixture-snapshot')
    journal.event(dict(event_id='first', user_id='u', product_id='p00', event_type='view'), 10.)
    assert runner.trigger(cfg, deferred)['status'] == 'WAITING_FOR_LABELS'
    journal.event(dict(event_id='unlinked', user_id='u', product_id='p00', event_type='view'), 11.)
    assert runner.trigger(cfg, deferred)['reason'] == 'retry_cooldown'
    assert len(calls) == 1
    now[0] += 300
    runner.trigger(cfg, deferred)
    assert len(calls) == 2
    now[0] += 300
    assert runner.trigger(cfg, deferred)['reason'] == 'unchanged_observations'
    assert len(calls) == 2 and registry.read() == before
