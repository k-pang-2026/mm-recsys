from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import yaml

from src.common.config import load_config
from src.ct.monitor import monitor
from src.ct.retrain_trigger import settings
from src.ct.storage import Journal


def test_utf8_overrides_legacy_encoding_without_polluting_json(tmp_path):
    code = ("from src.common.console import run_cli, log, emit_json; "
            "run_cli(lambda: (log('검색', '완료', '상품 3개', status='성공'), "
            "emit_json({'name': '한글 상품', 'total_count': 3})), '검사', '입력을 확인하세요.')")
    result = subprocess.run([sys.executable, '-c', code], capture_output=True,
                            env={**os.environ, 'PYTHONIOENCODING': 'ascii'})
    assert result.returncode == 0
    assert json.loads(result.stdout)['name'] == '한글 상품'
    assert '[검색 완료] [성공] 상품 3개' in result.stderr.decode('utf-8')
    assert '+00:00]' in result.stderr.decode('utf-8')
    path = tmp_path / '실행.log'
    path.write_bytes(result.stderr)
    assert '상품 3개' in path.read_text(encoding='utf-8')


@pytest.fixture
def api():
    # Transport contract fixture, not evidence of deployed model quality.
    calls = []
    recommendation = dict(user_id='한글사용자', recommendations=[dict(product_id='p', score=.1,
        reason='인기 상품', is_exploration=False)], pipeline_latency=dict(candidate_ms=1.25,
        ranking_ms=2.25, reranking_ms=.25, total_ms=3.75),
        session_context=dict(recent_clicks=[], session_interest=None))
    search = dict(search_type='text', results=[dict(product_id='p', name='한글 상품', score=.7, price=12300)],
                  latency_ms=4.25, total_count=1)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append((self.path, None))
            self.respond(recommendation)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append((self.path, body))
            if self.path == '/api/event':
                recommendation['session_context'] = dict(recent_clicks=['p'], session_interest=body['category'])
                self.respond(dict(applied=True, features=recommendation['session_context']))
            elif body.get('query_text') == '오류':
                self.respond(dict(detail='원본 입력 오류'), 422)
            else:
                self.respond(search)

        def respond(self, value, status=200):
            raw = json.dumps(value, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', calls, search
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def demo(url, command, *args):
    return subprocess.run([sys.executable, 'scripts/demo.py', command, '--api-url', url, '--json', *args],
                          capture_output=True, timeout=15)


def test_search_raw_json_and_summary_save_utf8(api, tmp_path):
    url, calls, original = api
    output = tmp_path / '검색.json'
    result = demo(url, 'search', '--query-text', '한글 검색', '--output', str(output))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == original == json.loads(output.read_text(encoding='utf-8'))
    assert calls[0][1]['query_text'] == '한글 검색'
    assert '응답 시간=4.2ms' in result.stderr.decode('utf-8')


def test_session_sends_actual_event_and_preserves_before_after(api):
    url, calls, _ = api
    result = demo(url, 'session', '--user-id', '한글사용자', '--product-id', 'p',
                  '--category', '상의', '--event-id', 'repeat-safe')
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload['before']['session_context']['recent_clicks'] == []
    assert payload['after']['session_context']['recent_clicks'] == ['p']
    assert calls[1][1]['event_id'] == 'repeat-safe'
    assert '후보 생성=1.2ms' in result.stderr.decode('utf-8')


def test_http_failure_keeps_original_body_traceback_and_next_action(api):
    result = demo(api[0], 'search', '--query-text', '오류')
    assert result.returncode != 0 and not result.stdout
    error = result.stderr.decode('utf-8')
    assert all(word in error for word in ['원본 입력 오류', 'HTTP 422', 'Traceback', '다음 조치'])


def test_ct_monitor_reports_actual_values_and_preserves_jsonl(tmp_path, capsys):
    cfg = load_config()
    spec = settings(cfg)
    spec.update(min_mature_requests=1, attribution_seconds=10, recent_seconds=100)
    journal = Journal(tmp_path / 'journal.sqlite3')
    journal.exposure('r', 'u', ['p'], 50, 'v1.0', 10.)
    output = tmp_path / 'ct.jsonl'
    result = monitor(journal, spec, 30., output)
    captured = capsys.readouterr()
    assert not captured.out
    assert 'HitRate@50=0.0' in captured.err and '성능 저하 감지' in captured.err
    saved = json.loads(output.read_text(encoding='utf-8'))
    assert {k: v for k, v in saved.items() if k != 'at'} == result


def test_ct_one_shot_stdout_is_one_json_document(tmp_path):
    cfg = load_config()
    cfg['paths'].update(model_dir=str(tmp_path / 'models'), results_dir=str(tmp_path / 'results'), by_scale={})
    config = tmp_path / 'config.yaml'
    config.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding='utf-8')
    result = subprocess.run([sys.executable, '-m', 'src.ct.retrain_trigger'], capture_output=True,
        env={**os.environ, 'CONFIG_PATH': str(config), 'SCALE': cfg['scale']}, timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['status'] == 'UNMEASURED'
    assert '모니터링 주기=' in result.stderr.decode('utf-8')


def test_tcp_benchmark_cannot_report_success_when_transport_is_unmeasured(monkeypatch, capsys):
    from src.recommendation import bench_ranking, bench_tcp
    monkeypatch.setattr(sys, 'argv', ['bench_ranking', '--tcp'])
    monkeypatch.setattr(bench_tcp, 'benchmark_tcp', lambda *args: dict(status='UNMEASURED', reason='bind denied'))
    assert bench_ranking.main() == 1
    assert json.loads(capsys.readouterr().out)['status'] == 'UNMEASURED'
