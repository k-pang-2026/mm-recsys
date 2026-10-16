from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

import pytest
import requests
from streamlit.testing.v1 import AppTest

import dashboard.data as data


@pytest.fixture
def report():
    values = dict(mrr=.6, ndcg_at_10=.45, recall_at_300=.8, auc=.96, hit_rate_at_50=.4,
        ndcg_at_50=.2, coverage=.3, search_p95_ms=250., recommend_p95_ms=80., candidate_p95_ms=10., feature_p95_ms=.2)
    targets = dict(mrr=.55, ndcg_at_10=.5, recall_at_300=.3, auc=.7, hit_rate_at_50=.2,
        ndcg_at_50=.08, coverage=.2, search_p95_ms=200., recommend_p95_ms=200., candidate_p95_ms=100., feature_p95_ms=10.)
    rows = [dict(name=k, value=v, target=targets[k], status='PASS' if (v <= targets[k] if k.endswith('_ms') else v >= targets[k]) else 'FAIL',
                 direction='max' if k.endswith('_ms') else 'min', split='benchmark' if k.endswith('_ms') else 'valid') for k, v in values.items()]
    arms = {arm: dict(users=20, cvr=v, ctr=.2, exploration_rate=0. if arm == 'control' else .2)
            for arm, v in [('control', .02), ('treatment', .01)]}
    risks = {name: dict(control=.6, treatment=.5, z_p_value=.2, chi_square_p_value=.2, low_expected_counts=False)
             for name in ('any_click', 'any_purchase')}
    return dict(version=data.VERSION, scale='dev', split='valid', quality_status='FAIL', acceptance='UNMEASURED',
        data_counts=dict(products=1000, users=100, events=5000), metrics=rows, model_version='fixture-v1', identity={},
        search=dict(status='MEASURED', per_mode={mode: dict(mrr=.6, ndcg_at_10=.45) for mode in ('text', 'image', 'hybrid')},
            bm25=dict(text=dict(mrr=.4, ndcg_at_10=.3), hybrid=dict(mrr=.4, ndcg_at_10=.3), image=dict(status='UNMEASURED')),
            tradeoff=[dict(mode=mode, parameter='efSearch', requested_value=32, vector_p95_ms=1., mrr=.6, ndcg_at_10=.45)
                      for mode in ('text', 'image', 'hybrid')]),
        recommendation=dict(status='MEASURED', cohort=dict(total_users=100, truth_users=80, cold=10),
            metrics={name: dict(hit_rate_at_50=.4, ndcg_at_50=.2, coverage=.3) for name in ('train_popularity', 'two_tower', 'deepfm', 'full_pipeline')},
            classification=dict(cvr=dict(auc=None, auc_status='UNDEFINED_SINGLE_CLASS', samples=200, positives=0))),
        ab=dict(status='MEASURED', days=30, arms=arms, inference=dict(cvr=dict(relative_lift=-.5, difference_ci95=[-.02, -.001], z_p_value=.01), independent_user_risks=risks)))


def offline(*args, **kwargs):
    return dict(ok=False, status_code=None, data=None, error='fixture: API unavailable')


def test_four_tabs_charts_and_metric_tables_match_json(tmp_path, monkeypatch, report):
    path = tmp_path / 'evaluation_dev_valid.json'
    path.write_text(json.dumps(report))
    monkeypatch.setenv('RESULTS_DIR', str(tmp_path))
    monkeypatch.setattr(data, 'api_call', offline)
    app = AppTest.from_file('dashboard/app.py', default_timeout=20).run()
    assert not app.exception
    assert [tab.label for tab in app.tabs] == ['검색', '추천', 'A/B 실험', '시스템']
    assert len(app.get('plotly_chart')) == 5
    metrics = {m.label: m.value for m in app.metric}
    assert metrics['측정 기준 판정'] == 'FAIL' and metrics['최종 종합 품질'] == 'UNMEASURED'
    assert metrics['CVR 상대 lift'] == '-50.00%' and metrics['API 연결'] == '연결 안 됨'
    observed = {}
    for frame in app.dataframe:
        df = frame.value
        if '측정값' in df:
            observed.update({row['지표']: (row['측정값'], row['판정']) for row in df.to_dict('records')})
    from dashboard.app import LABELS
    assert len(observed) == len(report['metrics'])
    for row in report['metrics']:
        assert observed[LABELS[row['name']]] == (row['value'], row['status'])
    spec = json.loads(app.get('plotly_chart')[0].proto.spec)
    assert spec['data'][0]['y'] == [.6, .6, .6]
    assert spec['data'][1]['y'] == [.4, None, .4]


def test_absent_and_malformed_results_render_without_fake_values(tmp_path, monkeypatch):
    monkeypatch.setenv('RESULTS_DIR', str(tmp_path))
    monkeypatch.setattr(data, 'api_call', offline)
    for content in (None, '{not JSON}', '{"version":"old"}'):
        if content is not None:
            (tmp_path / 'evaluation_dev_valid.json').write_text(content)
        app = AppTest.from_file('dashboard/app.py', default_timeout=20).run()
        assert not app.exception and len(app.tabs) == 4
        assert not app.get('plotly_chart')
        assert all(m.label not in ('측정 기준 판정', 'Control CVR') for m in app.metric)


def test_demos_use_shared_http_contract_and_empty_search_is_local(tmp_path, monkeypatch):
    monkeypatch.setenv('RESULTS_DIR', str(tmp_path))
    calls = []
    def api(url, method, route, **kwargs):
        calls.append((method, route, kwargs))
        if route == '/api/search':
            return dict(ok=True, data=dict(search_type='text', latency_ms=2., total_count=100,
                        results=[dict(product_id='p1', name='shirt', score=.8, price=1000)]))
        if route == '/api/recommend':
            return dict(ok=True, data=dict(recommendations=[dict(product_id='p2', score=.7, reason='popular')],
                        pipeline_latency=dict(total_ms=3.), session_context=dict(session_interest=None)))
        return offline()
    monkeypatch.setattr(data, 'api_call', api)
    app = AppTest.from_file('dashboard/app.py', default_timeout=20).run()
    next(b for b in app.button if b.label == '검색 실행').click().run()
    assert not any(route == '/api/search' for _, route, _ in calls)
    app.text_input(key='query_text').set_value(' black shirt ')
    next(b for b in app.button if b.label == '검색 실행').click().run()
    assert next(kwargs['payload'] for _, route, kwargs in calls if route == '/api/search') == dict(query_text='black shirt', top_k=10)
    next(b for b in app.button if b.label == '추천 실행').click().run()
    assert next(kwargs['params'] for _, route, kwargs in calls if route == '/api/recommend') == dict(user_id='U000001', top_n=10)
    assert not app.exception
    image = b'fixture image bytes; server validates decoding'
    assert base64.b64decode(data.search_payload('', image, 10)['query_image']) == image
    assert data.search_payload('shirt', image, 10)['query_text'] == 'shirt'
    with pytest.raises(ValueError):
        data.search_payload('', None, 10)


def test_dashboard_is_standalone_and_does_not_import_model_libraries():
    command = 'import sys; import dashboard.app; assert "torch" not in sys.modules; assert "faiss" not in sys.modules; print("standalone PASS")'
    result = subprocess.run([sys.executable, '-c', command], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_result_path_safety_nonfinite_values_and_read_only_io(tmp_path, monkeypatch, report):
    root = tmp_path / 'results'
    root.mkdir()
    path = root / 'evaluation_dev_valid.json'
    path.write_text(json.dumps(report))
    outside = tmp_path / 'outside.json'
    outside.write_text(json.dumps(report))
    with pytest.raises(ValueError, match='경로'):
        data.read_report(outside, root)
    for bad in (float('nan'), float('inf'), True):
        report['metrics'][0]['value'] = bad
        path.write_text(json.dumps(report))
        with pytest.raises(ValueError):
            data.read_report(path, root)
    report['metrics'][0]['value'] = .6
    path.write_text(json.dumps(report))
    (root / 'ct_log.jsonl').write_text('{"fixture":true}\ninvalid\n')
    def no_write(*args, **kwargs):
        raise AssertionError('dashboard must not write result files')
    monkeypatch.setattr(Path, 'write_text', no_write)
    monkeypatch.setattr(Path, 'write_bytes', no_write)
    assert data.read_report(path, root)['scale'] == 'dev'
    assert data.ct_log(root)['invalid_lines'] == 1


def test_api_unavailable_is_explicit(monkeypatch):
    def fail(*args, **kwargs):
        raise requests.ConnectionError('fixture outage')
    monkeypatch.setattr(requests.Session, 'request', fail)
    response = data.api_call('http://localhost:1', 'GET', '/health')
    assert not response['ok'] and response['status_code'] is None and response['data'] is None
    with pytest.raises(ValueError):
        data.api_call('http://localhost:1', 'POST', '/api/admin/reload')
