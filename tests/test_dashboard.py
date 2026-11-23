from __future__ import annotations

import base64
import json
from copy import deepcopy
import subprocess
import sys
from pathlib import Path

import pytest
import requests
import pandas as pd
import pyarrow as pa
from streamlit.testing.v1 import AppTest

import dashboard.data as data
from dashboard.formatting import display_value


def test_display_conversion_handles_timezone_rollover_without_mutating_values():
    original = dict(at='2026-11-11T18:07:08.123Z', other='2026-11-11T20:07:08+02:00',
        naive=pd.Timestamp('2026-11-11 18:07:08'), score=.9663299617,
        nested=[True, 300, None, 4.409705e-106], identifier='v1.0', date='2026-11-11',
        invalid='2026-99-99T00:00:00Z')
    before = deepcopy(original)
    shown = display_value(original)
    assert shown['at'] == shown['other'] == shown['naive'] == '2026-11-12 03:07:08 KST'
    assert shown['score'] == '1.0' and shown['nested'] == [True, 300, None, '4.4e-106']
    assert shown['identifier'] == 'v1.0' and shown['date'] == '2026-11-11'
    assert shown['invalid'] == original['invalid']
    assert display_value('2026-11-12T03:07:08+09:00') == shown['at']
    assert original == before


@pytest.fixture(autouse=True)
def isolated_published_results(tmp_path, monkeypatch):
    """Keep the repository's published bundles out of tests unless a test opts in."""
    monkeypatch.setenv('PUBLISHED_RESULTS_DIR', str(tmp_path / 'published'))
    monkeypatch.delenv('DASHBOARD_REFERENCE_REPORT', raising=False)


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


def flatten(node):
    for child in getattr(node, 'children', {}).values():
        yield child
        yield from flatten(child)


def part(app, name, kind):
    """Elements of one kind inside one category of the single page: between its heading and the next category's."""
    current, found = None, []
    for node in flatten(app.main):
        if getattr(node, 'type', None) == 'header':
            current = node.value
        elif current == name and getattr(node, 'type', None) == kind:
            found.append(node)
    return found


def texts(app, name, *kinds):
    return [node.value for kind in kinds for node in part(app, name, kind)]


def shown(app) -> str:
    """The measurement record every category reads, as picked in 개요 › 측정 기록."""
    return data.label(app.session_state['record_choice'], app.session_state['split_choice'])


def pick(app, record, split=None):
    """Choose a measurement record (and its scoring data) in the 개요 card."""
    app.radio(key='record').set_value(record).run()
    if split and any(item.key == 'split' for item in app.radio):
        app.radio(key='split').set_value(split).run()
    return app


def test_large_ct_log_reads_latest_utf8_records_and_preserves_invalid_count(tmp_path):
    path = tmp_path / 'ct_log.jsonl'
    with path.open('wb') as stream:
        stream.write(b'x' * 11_000_000 + b'\n')
        for i in range(120):
            stream.write((json.dumps(dict(index=i, message='학습 관측'), ensure_ascii=False) + '\n').encode())
        stream.write(b'\xff\n{"partial":')
    result = data.ct_log(tmp_path, limit=102)
    assert result['status'] == 'MEASURED' and not result['truncated']
    assert result['invalid_lines'] == 2
    assert [row['index'] for row in result['rows']] == list(range(20, 120))
    assert result['rows'][-1]['message'] == '학습 관측'
    path.write_bytes(b'x' * 11_000_000)
    assert data.ct_log(tmp_path)['truncated']
    with pytest.raises(ValueError):
        data.ct_log(tmp_path, limit=0)


@pytest.mark.parametrize('api_url,public_url,expected', [
    ('http://api-server:8000', '', 'http://localhost:19000'),
    ('http://api-server:8000', 'https://demo.example/api/', 'https://demo.example/api'),
    ('http://localhost:18000', '', 'http://localhost:18000'),
])
def test_browser_link_uses_public_address_without_changing_http_transport(tmp_path, monkeypatch, api_url, public_url, expected):
    (tmp_path / 'config.yaml').write_text('paths: {results_dir: results}\n')
    monkeypatch.setenv('CONFIG_PATH', str(tmp_path / 'config.yaml'))
    monkeypatch.setenv('API_URL', api_url)
    monkeypatch.setenv('PUBLIC_API_URL', public_url)
    monkeypatch.setenv('API_PORT', '19000')
    config = data.settings(tmp_path)
    assert config['api_url'] == api_url
    assert config['public_api_url'] == expected


def test_test_report_is_preferred_and_integration_receipt_is_visible(tmp_path, monkeypatch, report):
    (tmp_path / 'evaluation_dev_valid.json').write_text(json.dumps(report))
    report.update(split='test', integration=dict(stage='INTEGRATE', status='UNMEASURED'))
    (tmp_path / 'evaluation_dev_test.json').write_text(json.dumps(report))
    monkeypatch.setenv('RESULTS_DIR', str(tmp_path))
    monkeypatch.setattr(data, 'api_call', offline)
    app = AppTest.from_file('dashboard/app.py', default_timeout=20).run()
    assert not app.exception
    assert shown(app) == '이 컴퓨터에서 실행 (개발용 데이터) · 시험 데이터'
    assert app.radio(key='record').value == '이 컴퓨터에서 실행 (개발용 데이터)' and app.radio(key='split').value == '시험'
    assert next(m.value for m in part(app, '개요', 'metric') if m.label == '최종 종합 품질') == '미측정'
    assert '통합 검사 근거' in texts(app, '참고', 'subheader')  # the integration receipt has one home: 참고 › 통합 검사 근거
    assert any(item.label == '근거' for item in part(app, '참고', 'expander'))



def test_missing_full_test_falls_back_to_full_valid_before_dev(tmp_path, monkeypatch, report):
    (tmp_path / 'evaluation_dev_test.json').write_text(json.dumps(dict(report, split='test')))
    (tmp_path / 'evaluation_full_valid.json').write_text(json.dumps(dict(report, scale='full')))
    monkeypatch.setenv('RESULTS_DIR', str(tmp_path))
    monkeypatch.setenv('SCALE', 'full')
    monkeypatch.setattr(data, 'api_call', offline)
    app = AppTest.from_file('dashboard/app.py', default_timeout=20).run()
    assert not app.exception
    assert shown(app) == '이 컴퓨터에서 실행 (전체 데이터) · 검증 데이터'
    assert not any(item.key == 'split' for item in app.radio)  # one scoring data only: stated, not offered


def test_published_bundles_come_first_and_side_evidence_stays_inside_results(tmp_path, report):
    published, results = tmp_path / 'published', tmp_path / 'results'
    entry = data.PUBLISHED[2]
    path, folder = published / entry['path'], published / entry['folder']
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(dict(report, scale='full', split='test')))
    results.mkdir()
    config = dict(published_dir=published, results_dir=results, scale='full', reference_report=None)
    items, default = data.bundles(config)
    assert [item['label'] for item in items] == [data.label(entry['record'], entry['split'])]
    assert default == 0 and items[0]['folder'] == folder and items[0]['root'] == published
    assert data.read_json(data.evidence(items[0], 'data_audit.json'), published) is None
    (results / 'evaluation_dev_valid.json').write_text(json.dumps(report))
    (results / 'evaluation_full_test.json').write_text(json.dumps(dict(report, scale='full', split='test')))
    items, default = data.bundles(config)
    assert [item['label'] for item in items] == [data.label(entry['record'], entry['split']),
                                                 '이 컴퓨터에서 실행 (개발용 데이터) · 검증 데이터',
                                                 '이 컴퓨터에서 실행 (전체 데이터) · 시험 데이터']
    assert default == 2 and items[2]['root'] == results  # a finished runtime run of the configured scale wins
    outside = tmp_path.parent / 'outside_evidence.json'
    outside.write_text('{}')
    with pytest.raises(ValueError, match='경로'):
        data.read_json(outside, tmp_path)


def test_tabs_charts_and_metric_tables_match_json(tmp_path, monkeypatch, report):
    path = tmp_path / 'evaluation_dev_valid.json'
    path.write_text(json.dumps(report))
    monkeypatch.setenv('RESULTS_DIR', str(tmp_path))
    monkeypatch.setattr(data, 'api_call', offline)
    app = AppTest.from_file('dashboard/app.py', default_timeout=20).run()
    assert not app.exception
    from dashboard.app import LABELS, STATUS, fmt
    from dashboard.sections import TABS
    assert TABS == ['개요', '데이터', '검색', '추천', 'A/B 실험', '시스템', '직접 해보기', '참고']
    assert [item.value for item in app.header] == TABS  # one page: every category, one after another
    assert not any(item.key == 'tab' for item in app.radio)  # no tab bar
    assert not any(str(item.key).startswith('nav_') for item in app.button)  # and no category buttons
    assert any('상품 1,000개' in value for value in texts(app, '개요', 'markdown'))  # selected counts
    metrics = {m.label: m.value for m in part(app, '개요', 'metric')}
    assert metrics['측정 기준 판정'] == '미달' and metrics['최종 종합 품질'] == '미측정'
    assert metrics['MRR'] == '0.600' and metrics['검색 HTTP p95'] == '250.0ms'
    table = next(frame.value for frame in part(app, '개요', 'arrow_data_frame') if '측정값' in frame.value)
    observed = {row['지표']: (row['측정값'], row['판정']) for row in table.to_dict('records')}
    assert len(observed) == len(report['metrics'])
    for row in report['metrics']:
        assert observed[LABELS[row['name']]] == (fmt(row['name'], row['value']), STATUS[row['status']])
    charts = part(app, '검색', 'plotly_chart')
    assert len(charts) == 2 + 1  # MRR, NDCG@10, ANN (no HTTP samples)
    spec = json.loads(charts[0].proto.spec)
    assert spec['data'][0]['y'] == [.6, .6, .6]
    assert spec['data'][1]['y'] == [.4, None, .4]
    assert spec['data'][1]['text'][1] == '해당 없음'  # image mode has no BM25 (not a zero score)
    assert any('상대 -50.0%' in value for value in texts(app, 'A/B 실험', 'markdown'))
    assert any('모델 버전은 fixture-v1' in value for value in texts(app, '시스템', 'caption'))
    assert any('연결 안 됨' in value for value in texts(app, '직접 해보기', 'caption'))  # live API state sits with the demos



def test_contents_list_the_page_in_order_and_only_the_place_being_read_opens(tmp_path, monkeypatch, report):
    (tmp_path / 'evaluation_dev_valid.json').write_text(json.dumps(report))
    monkeypatch.setenv('RESULTS_DIR', str(tmp_path))
    monkeypatch.setattr(data, 'api_call', offline)
    from dashboard.sections import CATEGORIES, SECTIONS, TABS
    app = AppTest.from_file('dashboard/app.py', default_timeout=20).run()
    assert not app.exception and [item.value for item in app.header] == TABS
    complete = {'개요', '검색', '추천', '시스템', '직접 해보기', '참고'}  # categories whose every section has data in the fixture
    for tab in TABS:
        titles = [title for title, _ in SECTIONS[tab]]
        shown_titles = texts(app, tab, 'subheader')
        assert shown_titles == [title for title in titles if title in shown_titles], (tab, shown_titles)  # same names and order
        if tab in complete:
            assert shown_titles == titles, (tab, shown_titles)
    toc = ' '.join(item.value for item in app.sidebar.markdown)
    places = [anchor for tab in TABS for anchor in [CATEGORIES[tab]] + [anchor for _, anchor in SECTIONS[tab]]]
    positions = [toc.index(f'href="#{anchor}"') for anchor in places]
    assert positions == sorted(positions)  # the contents list every place in page order
    assert toc.count('toc-group open') == 1 and toc.index('toc-group open') < toc.index('href="#overview"')  # 개요 starts open



def test_absent_and_malformed_results_render_without_fake_values(tmp_path, monkeypatch):
    monkeypatch.setenv('RESULTS_DIR', str(tmp_path))
    monkeypatch.setattr(data, 'api_call', offline)
    from dashboard.sections import TABS
    for content in (None, '{not JSON}', '{"version":"old"}'):
        if content is not None:
            (tmp_path / 'evaluation_dev_valid.json').write_text(content)
        app = AppTest.from_file('dashboard/app.py', default_timeout=20).run()
        assert not app.exception and [item.value for item in app.header] == TABS
        assert not app.get('plotly_chart')
        assert all(m.label not in ('측정 기준 판정', 'Control CVR', 'CTR 상대 변화') for m in app.metric)



def test_background_reads_without_results(tmp_path, monkeypatch):
    monkeypatch.setenv('RESULTS_DIR', str(tmp_path))
    monkeypatch.setattr(data, 'api_call', offline)
    from dashboard.sections import SECTIONS
    app = AppTest.from_file('dashboard/app.py', default_timeout=20).run()
    assert not app.exception and not app.error, [item.value for item in app.error]
    assert texts(app, '개요', 'subheader') == [title for title, _ in SECTIONS['개요']]
    assert app.subheader[0].value == '프로젝트 소개'  # what the project is and aims for comes before any number
    assert not app.get('plotly_chart')
    text = ' '.join(texts(app, '개요', 'markdown'))
    assert '상품 50,000개' in text and '기준을 넘는지' in text
    from dashboard.guide import STORY
    story = next(value for value in texts(app, '개요', 'markdown') if 'class="story"' in value)
    assert [tab for tab, _, _ in STORY] == ['데이터', '검색', '추천', 'A/B 실험', '시스템']  # the five steps follow the page
    assert all(f'</span>{tab}</div><b>{goal}</b>' in story for tab, goal, _ in STORY)
    explained = {'데이터': '학습 train 80%', '검색': 'CLIP 모델이', '추천': '② 랭킹 · DeepFM'}  # how each part works, before any result
    for tab, phrase in explained.items():
        assert any(phrase in value for value in texts(app, tab, 'markdown')), tab
    text = ' '.join(texts(app, '참고', 'markdown'))
    for word in ('MRR', 'Recall@300', 'AUC', 'HitRate@50', 'Coverage', 'p95', 'CTR', 'p값'):  # every 개요 metric is explained
        assert word in text, word



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
    next(b for b in app.button if b.label == '추천 실행').click().run()  # both demos share the 직접 해보기 tab
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


def test_live_model_version_and_nested_ct_logs_are_distinct_from_saved_measurement(tmp_path, monkeypatch, report):
    (tmp_path / 'evaluation_dev_valid.json').write_text(json.dumps(report))
    (tmp_path / 'ct_log.jsonl').write_text(json.dumps(dict(event='promoted', scope='controlled_fixture',
        version='v1.1', at='2026-11-11T18:07:08.123Z', comparison=dict(candidate=dict(ctr_auc=.9)), hashes=dict(candidate='abc'))) + '\n' +
        json.dumps(dict(event='rollback', version='v1.0')) + '\n')
    monkeypatch.setenv('RESULTS_DIR', str(tmp_path))
    def api(url, method, route, **kwargs):
        return dict(ok=True, data=dict(status='ok' if route == '/health' else 'ready', model_version='v1.1'))
    monkeypatch.setattr(data, 'api_call', api)
    app = AppTest.from_file('dashboard/app.py', default_timeout=20).run()
    assert not app.exception
    status = next(value for value in texts(app, '직접 해보기', 'caption') if value.startswith('지금 API 상태'))
    assert '현재 모델 버전 v1.1' in status and '모델 버전 fixture-v1에서 측정' in status
    assert any('controlled_fixture' in value for value in texts(app, '시스템', 'caption'))
    curated = next(df for df in app.dataframe if '이벤트' in df.value)
    assert curated.value['이벤트'].tolist() == ['승격', '롤백']  # event codes shown in Korean
    assert pa.ipc.open_stream(curated.proto.styler.display_values).read_all().to_pandas()['시각'].iloc[0] == '2026-11-12 03:07:08 KST'
    frame = next(df.value for df in app.dataframe if 'event' in df.value)
    assert frame['comparison.candidate.ctr_auc'].iloc[0] == .9
    assert frame['at'].iloc[0] == '2026-11-11T18:07:08.123Z'
    element = next(df for df in app.dataframe if 'event' in df.value)
    shown = pa.ipc.open_stream(element.proto.styler.display_values).read_all().to_pandas()
    assert shown['at'].iloc[0] == '2026-11-12 03:07:08 KST'
    assert shown['comparison.candidate.ctr_auc'].iloc[0] == '0.9'


def test_packaged_report_renders_charts_then_prefers_new_runtime_measurement(tmp_path, monkeypatch, report):
    reference = Path('docs/submission/dashboard/evaluation_full_test.json').resolve()
    monkeypatch.setenv('DASHBOARD_REFERENCE_REPORT', str(reference))
    monkeypatch.setenv('RESULTS_DIR', str(tmp_path))
    monkeypatch.setenv('SCALE', 'full')
    monkeypatch.setattr(data, 'api_call', offline)
    app = AppTest.from_file('dashboard/app.py', default_timeout=20).run()
    assert not app.exception and shown(app) == '최종 제출 · 시험 데이터'
    assert any('Docker 이미지에 함께 넣은' in caption for caption in app.radio(key='record').proto.captions)
    assert any('지금 상품 그림으로 측정한' in value for value in texts(app, '개요', 'caption'))  # where it was measured
    for tab in ('검색', '추천', 'A/B 실험'):
        assert part(app, tab, 'plotly_chart'), tab
    archived = json.loads(reference.read_text())
    intervals = [spec for spec in (json.loads(chart.proto.spec) for chart in part(app, 'A/B 실험', 'plotly_chart'))
                 if spec['data'][0].get('error_x')]
    assert len(intervals) == 2
    for spec, metric in zip(intervals, ('ctr', 'cvr')):
        estimate = archived['ab']['inference'][metric]
        assert spec['data'][0]['x'] == pytest.approx([100 * estimate['difference']])
    assert any('고른 측정 기록의 A/B 실험' in value for value in texts(app, 'A/B 실험', 'caption'))

    report.update(scale='full', ab={'status': 'UNMEASURED'})
    live = tmp_path / 'evaluation_full_valid.json'
    live.write_text(json.dumps(report))
    with pytest.raises(ValueError, match='제출 보고서'):
        data.read_reference(live)
    app = AppTest.from_file('dashboard/app.py', default_timeout=20).run()
    assert not app.exception and shown(app) == '이 컴퓨터에서 실행 (전체 데이터) · 검증 데이터'
    assert next(metric.value for metric in part(app, '개요', 'metric') if metric.label == '측정 기준 판정') == '미달'
    assert not part(app, 'A/B 실험', 'plotly_chart')
    assert any('A/B는 시험 데이터 통합 실행에서 측정' in value for value in texts(app, 'A/B 실험', 'info'))
    report.update(data_fingerprint=archived['data_fingerprint'])
    report['recommendation']['models'] = archived['recommendation']['models']
    live.write_text(json.dumps(report))
    app.run()
    assert not app.exception and part(app, 'A/B 실험', 'plotly_chart')
    assert any('현재 배포의 A/B 측정 전' in value for value in texts(app, 'A/B 실험', 'caption'))


def test_repository_default_is_the_new_catalog_submission(monkeypatch):
    monkeypatch.delenv('PUBLISHED_RESULTS_DIR')
    monkeypatch.setattr(data, 'api_call', offline)
    app = AppTest.from_file('dashboard/app.py', default_timeout=30).run()
    assert not app.exception and shown(app) == '최종 제출 · 시험 데이터'
    records = app.radio(key='record')  # plain names, one per record, each with its date and use underneath
    assert records.options == ['최종 제출', '상품 그림 바꾸기 전', '통계 보정 실험']
    assert app.radio(key='split').options == ['시험 데이터', '검증 데이터']
    assert not app.error, [item.value for item in app.error]
    from dashboard.sections import TABS
    # Inputs that belong to 직접 해보기 only; the product lookup needs a local deployment, so it may be absent here.
    lookups = {'ledger_user', 'catalog_product', 'query_text', 'user_id'}
    for tab in TABS:
        inputs = {item.key for item in part(app, tab, 'text_input')}
        assert lookups - {'catalog_product'} <= inputs if tab == '직접 해보기' else not inputs & lookups, (tab, inputs)


def test_record_picked_in_overview_applies_to_every_category(monkeypatch):
    monkeypatch.delenv('PUBLISHED_RESULTS_DIR')
    monkeypatch.setattr(data, 'api_call', offline)
    app = pick(AppTest.from_file('dashboard/app.py', default_timeout=30).run(), '상품 그림 바꾸기 전', '검증')
    assert not app.exception and shown(app) == '상품 그림 바꾸기 전 · 검증 데이터'
    for tab in ('데이터', '검색', '추천', 'A/B 실험', '시스템', '참고'):  # each says which record its numbers come from
        assert any('지금 보고 있는 기록: 상품 그림 바꾸기 전 · 검증 데이터' in value for value in texts(app, tab, 'markdown')), tab
    assert app.radio(key='record').value == '상품 그림 바꾸기 전' and app.radio(key='split').value == '검증'
    pick(app, '통계 보정 실험')  # 시험 data only: stated in the card instead of a switch
    assert shown(app) == '통계 보정 실험 · 시험 데이터' and not any(item.key == 'split' for item in app.radio)
    assert any('이 기록에는 하나만 있습니다' in value for value in texts(app, '개요', 'markdown'))


def test_every_published_bundle_shows_an_ab_with_its_source(monkeypatch):
    monkeypatch.delenv('PUBLISHED_RESULTS_DIR')
    monkeypatch.setattr(data, 'api_call', offline)
    for entry in data.PUBLISHED:
        label = data.label(entry['record'], entry['split'])
        app = pick(AppTest.from_file('dashboard/app.py', default_timeout=30).run(), entry['record'], entry['split'])
        assert shown(app) == label
        assert not app.exception and not app.error and part(app, 'A/B 실험', 'plotly_chart'), label
        captions = texts(app, 'A/B 실험', 'caption')
        assert any('고른 측정 기록의 A/B 실험' in text or '같은 데이터·추천 모델' in text for text in captions), label


def test_paired_ab_requires_the_same_data_and_models(tmp_path, report):
    models = {kind: {'hashes': {'weights': kind}} for kind in ('candidate', 'ranking', 'session')}
    report.update(data_fingerprint='same', recommendation=dict(report.get('recommendation', {}), models=models))
    measured = dict(deepcopy(report), split='test')
    measured['ab'] = dict(report['ab'], status='MEASURED')
    root = tmp_path / 'docs' / 'results'
    path = root / 'paired' / 'evaluation_full_test.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(measured))
    bundle = dict(root=root, ab=path)
    ab, caption = data.paired_ab(dict(report, ab={'status': 'UNMEASURED'}), bundle)
    assert ab['status'] == 'MEASURED' and '시험 데이터 결과의 A/B' in caption
    assert caption.split(' · ')[1] == 'docs/results/paired/evaluation_full_test.json'
    assert data.paired_ab(dict(report, data_fingerprint='other'), bundle) is None
    changed = deepcopy(report)
    changed['recommendation']['models']['ranking'] = {'hashes': {'weights': 'other'}}
    assert data.paired_ab(changed, bundle) is None
    path.write_text(json.dumps(dict(measured, split='valid')))
    assert data.paired_ab(report, bundle) is None
    assert data.paired_ab(report, dict(root=root, ab=root / 'missing.json')) is None
    assert data.paired_ab(report, None) is None


def test_reference_compares_data_search_and_active_recommender(tmp_path):
    from dashboard.assets import reference_identity
    from src.common.artifacts import file_hash, write_json
    models, results = tmp_path / 'models', tmp_path / 'results'
    write_json(tmp_path / 'split_manifest.json', {'generation_fingerprint': 'same'})
    write_json(results / 'deployment.json', dict(data_fingerprint='same', data_dir=str(tmp_path),
                                                model_dir=str(models), search_subdir='search'))
    write_json(models / 'registry.json', {'active': 'v1.0'})
    bundles = {}
    for kind, folder in [('candidate', ''), ('ranking', 'ranking'), ('session', 'session')]:
        bundles[kind] = {'hashes': {'weights': kind}}
        write_json(models / 'v1.0' / folder / 'meta.json', bundles[kind])
    search = {'embeddings': {'fingerprint': 'e', 'files': {'text.npy': 'vector-hash'}},
              'index': {'fingerprint': 'i', 'files': {'text.faiss': 'index-hash'}}}
    for key, directory in [('embeddings', 'embeddings'), ('index', 'indexes')]:
        identity = search[key]['fingerprint']
        write_json(models / 'search' / f'{directory}_current.json', {'fingerprint': identity})
        write_json(models / 'search' / directory / identity / 'manifest.json', search[key])
    report = dict(model_version='v1.0', data_fingerprint='same', search={'models': search},
                  identity={'data_manifest_sha256': file_hash(tmp_path / 'split_manifest.json')},
                  recommendation={'models': bundles})
    assert '일치합니다' in reference_identity(report, results)
    index_manifest = models / 'search/indexes/i/manifest.json'
    write_json(index_manifest, {'fingerprint': 'i', 'files': {'text.faiss': 'rebuilt-index-hash'}})
    assert '검색 파일 해시는 최종 제출 기록과 다릅니다' in reference_identity(report, results)
    write_json(index_manifest, search['index'])
    from src.common.artifacts import fingerprint
    recipe = {'candidate': {'max_grad_norm': 10.0}}
    expected_index = {'config_fingerprint': fingerprint({'candidate': {}}), 'index_sha256': 'same-index'}
    report['recommendation']['models']['index'] = expected_index
    bundles['candidate']['hashes']['index_manifest.json'] = 'legacy-manifest'
    write_json(models / 'registry.json', {'active': 'v1.0', 'versions': {'v1.0': {'config': {'recommend': recipe}}}})
    index_path = models / 'v1.0/index_manifest.json'
    active_index = dict(expected_index, config_fingerprint=fingerprint(recipe))
    for digest, expected_text in [('different-index', '추천 모델 산출물은 최종 제출 기록과 다릅니다'), ('same-index', '일치합니다')]:
        write_json(index_path, dict(active_index, index_sha256=digest))
        write_json(models / 'v1.0/meta.json', {'hashes': {**bundles['candidate']['hashes'], 'index_manifest.json': file_hash(index_path)}})
        assert expected_text in reference_identity(report, results)
    write_json(models / 'search/indexes_current.json', {'fingerprint': 'other'})
    assert '검색 번들은 최종 제출 기록과 다릅니다' in reference_identity(report, results)
    write_json(models / 'registry.json', {'active': 'v2.0'})
    assert '활성 모델 버전' in reference_identity(report, results)
    report['data_fingerprint'] = 'other'
    assert '다른 데이터' in reference_identity(report, results)

def test_changed_reranking_policy_marks_old_measurements(tmp_path):
    from dashboard.assets import different_recommendation_policy
    from src.common.artifacts import write_json
    sources = {'src/recommendation/reranking.py':'new'}
    report = {'identity':{'source_hashes':dict(sources)}}
    write_json(tmp_path/'deployment.json', {'recommendation_policy_sources':sources})
    assert not different_recommendation_policy(report, tmp_path)
    report['identity']['source_hashes']['src/recommendation/reranking.py'] = 'old'
    assert different_recommendation_policy(report, tmp_path)


def test_ab_display_requires_the_deployed_reranking_policy(tmp_path):
    from dashboard.assets import ab_result
    from src.common.artifacts import write_json

    data = tmp_path / 'data'
    models = tmp_path / 'models'
    policy = {'src/recommendation/reranking.py': 'current'}
    write_json(data / 'split_manifest.json', {'generation_fingerprint': 'same'})
    write_json(tmp_path / 'deployment.json', dict(data_dir=str(data), model_dir=str(models),
               data_fingerprint='same', recommendation_policy_sources=policy))
    bundles = {k: {'hashes': {'weights': k}} for k in ('candidate', 'ranking', 'session')}
    for kind, subdir in [('candidate', ''), ('ranking', 'ranking'), ('session', 'session')]:
        write_json(models / 'v1.0' / subdir / 'meta.json', bundles[kind])
    write_json(tmp_path / 'ab_test.json', dict(status='PASS', identity=dict(
        data_fingerprint='same', bundle_metadata=bundles, source_hashes={next(iter(policy)): 'old'})))
    assert ab_result(tmp_path) is None
    report = dict(ab=dict(status='MEASURED', run_id='current-run'), data_fingerprint='same',
                  identity=dict(source_hashes=policy), recommendation=dict(models=bundles))
    write_json(tmp_path / 'evaluation_full_test.json', report)
    assert ab_result(tmp_path)['run_id'] == 'current-run'
    report['recommendation']['models']['ranking'] = {'hashes': {'weights': 'other'}}
    write_json(tmp_path / 'evaluation_full_test.json', report)
    assert ab_result(tmp_path) is None
