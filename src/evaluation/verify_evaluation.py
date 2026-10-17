"""Verify B8 measurement provenance, accounting and real dashboard rendering."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from src.common.artifacts import file_hash, fingerprint, write_json
from src.common.config import load_config
from src.evaluation.run_all import ab_evidence, check_frozen, input_identity, metric_rows
from src.evaluation.reporting import quality_status


def verify(path: Path, cfg: dict) -> dict:
    report = json.loads(path.read_text())
    manifest = json.loads((Path(cfg['paths']['data_dir']) / 'split_manifest.json').read_text())
    if (report['status'] != 'PASS' or report['identity']['config_fingerprint'] != fingerprint(cfg)
            or report['identity']['data_fingerprint'] != manifest['generation_fingerprint']
            or report['identity']['data_hashes'] != manifest['file_hashes']):
        raise ValueError('measurement configuration/dataset mismatch')
    inputs = input_identity(cfg)
    if report['source_hashes'] != inputs['source_hashes']:
        raise ValueError('measurement source changed')
    expected = metric_rows(cfg, report['split'], report['search'], report['recommendation'],
                          report['api'], report['candidate_latency'], report['feature_store'])
    if report['metrics'] != expected or any(row['value'] is None for row in expected):
        raise ValueError('required metrics missing or inconsistent')
    quality = quality_status(expected, report['recommendation'], cfg['recommend']['candidate_k'])
    if report['quality_status'] != quality:
        raise ValueError('quality status differs from unchanged thresholds')
    rec = report['recommendation']
    required_users = min(cfg['recommend']['evaluation']['coverage_users'], manifest['counts']['users'])
    if rec['cohort']['total_users'] != required_users:
        raise ValueError('coverage population differs from fixed configured cohort')
    for row in rec['metrics'].values():
        if (row['coverage_users'] != required_users or row['catalog_items'] != manifest['counts']['products']
                or row['coverage'] != row['unique_recommended_items'] / row['catalog_items']):
            raise ValueError('coverage denominator or cohort differs')
    if rec['candidate']['ann_two_tower']['candidate_count_min'] != min(300, rec['cohort']['eligible_catalog']):
        raise ValueError('candidate count differs from the top300 contract')
    for row in report['search']['per_mode'].values():
        if row['queries'] != cfg['search']['evaluation']['queries_per_mode']:
            raise ValueError('query cohort changed')
    for mode, row in report['api']['modes'].items():
        if row['warmup'] < 10 or row['requests'] < 100 or row['errors'] != 0:
            raise ValueError(f'{mode}: insufficient successful serial requests')
        samples = row['http_samples_ms']
        if len(samples) != row['requests'] or not np.isfinite(samples).all() or min(samples) < 0:
            raise ValueError('invalid HTTP sample accounting')
        if row['http']['p95_ms'] != float(np.percentile(samples, 95)):
            raise ValueError('HTTP percentile mismatch')
    feature = report['feature_store']
    if (feature['warmup'] < 10 or feature['requests'] < 100 or feature['profile_hits'] != feature['requests']
            or feature['latency_ms']['p95'] != float(np.percentile(feature['samples_ms'], 95))):
        raise ValueError('Redis measurements include missing profiles or inconsistent samples')
    if report['ab'] != ab_evidence(cfg, manifest, rec['models']):
        raise ValueError('A/B evidence changed')
    frozen = json.loads((Path(cfg['paths']['results_dir']) / f'evaluation_selection_{cfg["scale"]}.json').read_text())
    check_frozen(frozen, inputs)
    return dict(status='PASS', scale=report['scale'], split=report['split'], acceptance='UNMEASURED',
                source=str(path), sha256=file_hash(path), data_fingerprint=manifest['generation_fingerprint'],
                measured_metrics=len(expected), quality_status=quality,
                checks='configuration/data/model recipe/source hashes, immutable valid evidence, coverage cohort/denominator, query/candidate counts, raw serial HTTP/Redis percentiles, A/B source')


def verify_dashboard(report_path: Path, url: str) -> dict:
    import httpx
    from streamlit.testing.v1 import AppTest
    from dashboard.app import LABELS
    from dashboard.data import api_call, search_payload, settings
    with httpx.Client(timeout=5, trust_env=False) as client:
        health = client.get(url.rstrip('/') + '/_stcore/health')
        home = client.get(url)
    if health.status_code != 200 or health.text.strip() != 'ok' or home.status_code != 200:
        raise ValueError('real Streamlit HTTP server is not healthy')
    report = json.loads(report_path.read_text())
    app = AppTest.from_file('dashboard/app.py', default_timeout=30).run()
    if app.exception or [tab.label for tab in app.tabs] != ['검색', '추천', 'A/B 실험', '시스템']:
        raise ValueError('four dashboard tabs did not render')
    frames = {}
    for element in app.dataframe:
        df = element.value
        if '측정값' in df:
            frames.update({row['지표']: (row['측정값'], row['판정']) for row in df.to_dict('records')})
    for row in report['metrics']:
        if frames.get(LABELS[row['name']]) != (row['value'], row['status']):
            raise ValueError(f'dashboard value/status differs from JSON: {row["name"]}')
    if len(app.get('plotly_chart')) != 5:
        raise ValueError('expected search/tradeoff/recommendation/A-B/system charts')
    app.text_input(key='query_text').set_value('black shirt')
    next(button for button in app.button if button.label == '검색 실행').click().run()
    if app.exception or not any('product_id' in item.value and 'name' in item.value and len(item.value) == 10 for item in app.dataframe):
        raise ValueError('live text search demo did not render ten results')
    next(button for button in app.button if button.label == '추천 실행').click().run()
    if app.exception or not any('product_id' in item.value and 'reason' in item.value and len(item.value) == 10 for item in app.dataframe):
        raise ValueError('live recommendation demo did not render ten results')
    config = settings(Path.cwd())
    cfg = load_config()
    image_path = next((Path(cfg['paths']['data_dir']) / 'images').glob('*.jpg'))
    for text, mode in [('', 'image'), ('black shirt', 'hybrid')]:
        response = api_call(config['api_url'], 'POST', '/api/search',
                            payload=search_payload(text, image_path.read_bytes(), 10), timeout=30)
        if not response['ok'] or response['data']['search_type'] != mode or len(response['data']['results']) != 10:
            raise ValueError(f'live {mode} demo request failed')
    return dict(status='PASS', streamlit_url=url, health_http_status=health.status_code,
                homepage_http_status=home.status_code, tabs=[tab.label for tab in app.tabs],
                chart_count=len(app.get('plotly_chart')), matched_metrics=len(report['metrics']),
                demos=dict(text_form='PASS: 10 results', recommendation_form='PASS: 10 results',
                           image_api='PASS: 10 results', hybrid_api='PASS: 10 results', sample_image_sha256=file_hash(image_path)),
                method='real Streamlit HTTP health/home + Streamlit AppTest component-tree rendering and JSON/table equality')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--split', choices=['valid', 'test'], default='valid')
    parser.add_argument('--dashboard-url')
    args = parser.parse_args()
    cfg = load_config()
    root = Path(cfg['paths']['results_dir'])
    path = root / f'evaluation_{cfg["scale"]}_{args.split}.json'
    result = verify(path, cfg)
    if args.dashboard_url:
        result['dashboard'] = verify_dashboard(path, args.dashboard_url)
    output = root / 'experiments' / 'C' / f'evaluation_verification_{cfg["scale"]}_{args.split}.json'
    write_json(output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
