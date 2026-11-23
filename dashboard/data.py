"""Dashboard I/O uses only standalone dashboard image dependencies."""
from __future__ import annotations

import json
import math
import os
import re
import base64
from pathlib import Path
from urllib.parse import urlsplit

from src.common.artifacts import file_hash

import requests
import yaml
from dotenv import dotenv_values

VERSION = 'evaluation-dashboard-v1'


def settings(root: Path) -> dict:
    path = Path(os.getenv('CONFIG_PATH', 'config.yaml'))
    path = path if path.is_absolute() else root / path
    cfg = yaml.safe_load(path.read_text(encoding='utf-8'))
    scale = os.getenv('SCALE', cfg.get('scale', 'dev'))
    paths = {**cfg['paths'], **cfg['paths'].get('by_scale', {}).get(scale, {})}
    configured = Path(os.getenv('RESULTS_DIR', paths['results_dir']))
    defaults = dotenv_values(root / '.env') if (root / '.env').is_file() else {}
    api_url = (os.getenv('API_URL') or defaults.get('API_URL') or 'http://localhost:8000').rstrip('/')
    public_api_url = os.getenv('PUBLIC_API_URL') or defaults.get('PUBLIC_API_URL')
    if not public_api_url:
        port = os.getenv('API_PORT') or defaults.get('API_PORT') or '8000'
        public_api_url = f'http://localhost:{port}' if urlsplit(api_url).hostname == 'api-server' else api_url
    serving_path = root / 'config' / 'serving.yaml'
    serving = yaml.safe_load(serving_path.read_text(encoding='utf-8')) if serving_path.is_file() else {}
    serving_ct: dict = next((v['ct'] for v in (serving or {}).values() if isinstance(v, dict) and isinstance(v.get('ct'), dict)), {})
    reference = os.getenv('DASHBOARD_REFERENCE_REPORT')
    published = Path(os.getenv('PUBLISHED_RESULTS_DIR', 'docs/results'))
    return dict(reference_report=root / reference if reference else None,
                published_dir=published if published.is_absolute() else root / published,
                results_dir=configured if configured.is_absolute() else root / configured,
                api_url=api_url, public_api_url=public_api_url.rstrip('/'),
                api_timeout=float(os.getenv('DASHBOARD_API_TIMEOUT', '10')),
                scale=scale,
                taxonomy=cfg.get('simulator', {}).get('taxonomy', {}),
                ct={**cfg.get('ct', {}), **serving_ct})


def available_reports(root: Path) -> list[Path]:
    return sorted((p for p in root.glob('evaluation_*_*.json')
                   if re.fullmatch(r'evaluation_(dev|full)_(valid|test)\.json', p.name)), key=lambda p: p.name)


# Published result bundles (relative to published_dir = docs/results, independent of the runtime results_dir).
# Each is a measurement record (`record`, named in plain words) scored on 시험 or 검증 data (`split`).
# The folder holds the bundle's side evidence (data_audit, latency_conditions, CT records); `files` overrides a
# side-evidence file kept elsewhere. `reference` reports are verified against their .sha256. `ab` names the A/B
# measured on the same data and recommendation models when the report itself stores none (paired_ab checks the
# identity before it is shown). Missing bundles are skipped.
ILLUSTRATIONS = 'experiments/A/illustrations_v1/integration_current'
ILLUSTRATIONS_FILES = {'data_audit.json': f'{ILLUSTRATIONS}/cold_data_audit.json',
                       'quality_full_valid.json': f'{ILLUSTRATIONS}/release_quality/quality_full_valid.json'}
FINAL, BEFORE_IMAGES, CALIBRATED = '최종 제출', '상품 그림 바꾸기 전', '통계 보정 실험'
# One line under each record name in the picker.
RECORD_NOTES = {FINAL: '11/21 · 기본으로 보여 주는 기록',
                BEFORE_IMAGES: '11/12 · 비교용 · 상품 그림을 바꾸기 전에 같은 방식으로 측정',
                CALIBRATED: '11/15 · 비교용 · 실제 쇼핑 통계에 맞춰 바꾼 데이터로 측정'}
PUBLISHED = (
    dict(record=FINAL, split='시험', path=f'{ILLUSTRATIONS}/release_display/evaluation_full_test.json',
         folder=ILLUSTRATIONS, files=ILLUSTRATIONS_FILES, reference=True),
    dict(record=FINAL, split='검증', path=f'{ILLUSTRATIONS}/release_quality/quality_full_valid.json',
         folder=ILLUSTRATIONS, files=ILLUSTRATIONS_FILES, ab=f'{ILLUSTRATIONS}/release_display/evaluation_full_test.json'),
    dict(record=BEFORE_IMAGES, split='시험', path='experiments/A/final_validation_20261112/published/evaluation_full_test.json',
         folder='experiments/A/final_validation_20261112'),
    dict(record=BEFORE_IMAGES, split='검증', path='experiments/A/final_validation_20261112/quality_full_valid.json',
         folder='experiments/A/final_validation_20261112',
         ab='experiments/A/final_validation_20261112/published/evaluation_full_test.json'),
    dict(record=CALIBRATED, split='시험', path='experiments/A/realism_full_20261115/quality/quality_full_test.json',
         folder='experiments/A/realism_full_20261115', ab='experiments/A/realism_full_20261115/ab_test.json'),
)
REQUIREMENTS = 'integration/20261107_requirements/requirements.json'
REALISM = 'experiments/A/realism_full_20261115/realism_distance.json'
DEEPFASHION = 'external/expansion-v3/deepfashion_expanded.json'
SPLIT_LABEL = dict(test='시험', valid='검증')


def label(record: str, split: str) -> str:
    return f'{record} · {split} 데이터'


def bundles(config: dict) -> tuple[list[dict], int]:
    """Published bundles, an optional packaged reference, then runtime reports; returns the list and the default index.

    A finished runtime evaluation for the configured scale is selected first, as in the Docker README; otherwise the
    newest published bundle is the default.
    """
    published: Path = config['published_dir']
    items = []
    for entry in PUBLISHED:
        path = published / entry['path']
        if path.is_file():
            items.append(dict(record=entry['record'], split=entry['split'], note=RECORD_NOTES[entry['record']],
                              label=label(entry['record'], entry['split']), path=path, folder=published / entry['folder'],
                              root=published, files={name: published / rel for name, rel in entry.get('files', {}).items()},
                              reference=entry.get('reference', False),
                              ab=published / entry['ab'] if entry.get('ab') else None))
    reference: Path | None = config.get('reference_report')
    if reference and reference.is_file() and not any(item['reference'] for item in items):
        items.insert(0, dict(record=FINAL, split='시험', note='Docker 이미지에 함께 넣은 최종 제출 기록', label=label(FINAL, '시험'),
                             path=reference, folder=reference.parent, root=reference.parent, files={}, reference=True, ab=None))
    results: Path = config['results_dir']
    runtime = available_reports(results) if results.is_dir() else []
    first_runtime = len(items)
    for path in runtime:
        size, split = path.stem.split('_')[1:]
        record = f"이 컴퓨터에서 실행 ({'개발용 데이터' if size == 'dev' else '전체 데이터'})"
        items.append(dict(record=record, split=SPLIT_LABEL[split], note='results 폴더에 저장된 직접 실행 결과',
                          label=label(record, SPLIT_LABEL[split]), path=path, folder=results, root=results, files={},
                          reference=False, ab=None))
    preferred = next((first_runtime + i for split in ('test', 'valid') for i, path in enumerate(runtime)
                      if path.name == f'evaluation_{config["scale"]}_{split}.json'), 0)
    return items, preferred


def evidence(bundle: dict | None, name: str) -> Path | None:
    """Side-evidence path for a bundle (override first, then the bundle folder)."""
    if not bundle:
        return None
    return bundle.get('files', {}).get(name) or bundle['folder'] / name


def ab_record(value: dict, path: Path) -> dict:
    """Dashboard view of an ab_test.json written by the A/B runner (per-user arm statistics dropped)."""
    return dict(status='MEASURED', source=str(path), run_id=value.get('run_id'), days=value['days'], seed=value['seed'],
        strategies=value['strategies'], denominators=value['denominators'], inference=value['inference'],
        arms={key: {k: v for k, v in row.items() if k != 'arm_statistics'} for key, row in value['arms'].items()},
        limitations=value['limitations'])


def _same_models(measured: dict, report: dict) -> bool:
    models = report.get('recommendation', {}).get('models') or {}
    return all(measured.get(kind, {}).get('hashes') is not None
               and measured[kind]['hashes'] == models.get(kind, {}).get('hashes')
               for kind in ('candidate', 'ranking', 'session'))


def paired_ab(report: dict, bundle: dict | None) -> tuple[dict, str] | None:
    """A/B stored for the same data fingerprint and recommendation models as a bundle whose report has none.

    Returns the A/B and a caption naming where it came from, or None when nothing matching is stored.
    """
    path: Path | None = (bundle or {}).get('ab')
    if path is None or not path.is_file():
        return None
    value = read_json(path, bundle['root'])
    shown = path.relative_to(bundle['root'].parent.parent) if path.is_relative_to(bundle['root'].parent.parent) else path
    if value.get('version') == VERSION:  # an evaluation report that embeds the A/B (the paired test split)
        ab = value.get('ab', {})
        if ab.get('status') != 'MEASURED' or value.get('split') != 'test':
            return None
        fingerprint, models = value.get('data_fingerprint'), value.get('recommendation', {}).get('models') or {}
        source = (value.get('measurement_sources', {}).get('ab')
                  or value.get('integration', {}).get('checks', {}).get('ab_statistics') or {}).get('source')
        caption = ('이 기록에는 A/B가 없어 같은 데이터·추천 모델로 측정한 시험 데이터 결과의 A/B를 표시합니다 · '
                   f"{shown}" + (f' · A/B 원자료 {source}' if source else ''))
        ab = dict(ab, source=source or str(shown))
    else:  # an ab_test.json kept next to the report
        if value.get('status') != 'PASS':
            return None
        fingerprint = value.get('identity', {}).get('data_fingerprint')
        models = value.get('identity', {}).get('bundle_metadata') or {}
        ab = ab_record(value, shown)
        caption = f'이 기록에는 A/B가 없어 같은 폴더에 저장된 같은 데이터·추천 모델의 A/B 실행 기록을 표시합니다 · {shown}'
    if fingerprint != report.get('data_fingerprint') or not _same_models(models, report):
        return None
    return ab, caption


def load_bundle(bundle: dict) -> dict:
    return read_reference(bundle['path']) if bundle.get('reference') else read_report(bundle['path'], bundle['root'])


def read_json(path: Path, root: Path, limit: int = 20_000_000):
    """Read side evidence inside results_dir; None when the file is absent."""
    if not path.is_file():
        return None
    if not path.resolve().is_relative_to(root.resolve()) or path.stat().st_size > limit:
        raise ValueError('결과 파일 경로 또는 크기를 확인하세요.')
    return json.loads(path.read_text(encoding='utf-8'))


def read_report(path: Path, root: Path) -> dict:
    if not path.resolve().is_relative_to(root.resolve()) or path.stat().st_size > 5_000_000:
        raise ValueError('결과 파일 경로 또는 크기를 확인하세요.')
    value = json.loads(path.read_text(encoding='utf-8'))
    if value.get('version') != VERSION or value.get('scale') not in ('dev', 'full') or value.get('split') not in ('valid', 'test'):
        raise ValueError('지원하지 않는 평가 결과 형식입니다.')
    metrics = value.get('metrics')
    if not isinstance(metrics, list) or len({row['name'] for row in metrics}) != len(metrics):
        raise ValueError('평가 지표 목록이 올바르지 않습니다.')
    for row in metrics:
        measured = row.get('value')
        if measured is None:
            if row.get('status') != 'UNMEASURED':
                raise ValueError('미측정 값의 상태가 올바르지 않습니다.')
        elif isinstance(measured, bool) or not isinstance(measured, (float, int)) or not math.isfinite(measured):
            raise ValueError('평가 값은 유한한 숫자여야 합니다.')
        if row.get('status') not in ('PASS', 'FAIL', 'UNMEASURED', 'MEASURED'):
            raise ValueError('평가 판정이 올바르지 않습니다.')
    if value.get('quality_status') not in ('PASS', 'FAIL', 'UNMEASURED') or value.get('acceptance') not in ('PASS', 'FAIL', 'UNMEASURED'):
        raise ValueError('종합 판정이 올바르지 않습니다.')
    counts = value.get('data_counts', {})
    if any(type(counts.get(key)) is not int or counts[key] < 0 for key in ('products', 'users', 'events')):
        raise ValueError('평가 데이터 개수가 없습니다.')
    return value


def read_reference(path: Path) -> dict:
    report = read_report(path, path.parent)
    integration = report.get('integration', {})
    sources = report.get('measurement_sources') or {}
    measured = (report['acceptance'] == 'UNMEASURED'
                and all(sources.get(key, {}).get('sha256') for key in ('quality', 'ab'))
                and report.get('test_used_for_selection') is False)
    integrated = (integration.get('stage') == 'INTEGRATE'
                  and integration.get('frozen_quality', {}).get('source')
                  and integration.get('checks', {}).get('ab_statistics', {}).get('source'))
    if (report['scale'] != 'full' or report['split'] != 'test'
            or not (measured or integrated) or report.get('ab', {}).get('status') != 'MEASURED'):
        raise ValueError('full test 평가와 A/B 근거가 연결된 제출 보고서가 필요합니다.')
    if path.with_suffix('.sha256').read_text().split() != [file_hash(path), path.name]:
        raise ValueError('기준 보고서의 체크섬이 다릅니다.')
    return report


def search_payload(text: str, image: bytes | None, top_k: int) -> dict:
    if type(top_k) is not int or not 1 <= top_k <= 100:
        raise ValueError('검색 결과 수는 1~100이어야 합니다.')
    if not text.strip() and not image:
        raise ValueError('검색어나 이미지를 입력하세요.')
    if image is not None and len(image) > 5_000_000:
        raise ValueError('검색 이미지는 5MB 이하여야 합니다.')
    payload: dict = dict(top_k=top_k)
    if text.strip():
        payload['query_text'] = text.strip()
    if image:
        payload['query_image'] = base64.b64encode(image).decode()
    return payload


def ct_log(root: Path, limit: int = 100, name: str = 'ct_log.jsonl') -> dict:
    if limit < 1:
        raise ValueError('CT log limit must be positive')
    path = root / name
    if not path.is_file():
        return dict(status='UNMEASURED', rows=[], invalid_lines=0)
    with path.open('rb') as stream:
        position = stream.seek(0, os.SEEK_END)
        remaining = min(position, 10_000_000)
        chunks, newlines = [], 0
        while remaining and newlines <= limit:
            size = min(65536, remaining)
            position -= size; remaining -= size
            stream.seek(position)
            block = stream.read(size)
            chunks.append(block); newlines += block.count(b'\n')
    lines = b''.join(reversed(chunks)).split(b'\n')
    if position:
        lines = lines[1:]  # The first chunk may start inside a UTF-8/JSON record.
    if lines and not lines[-1]:
        lines.pop()
    rows, invalid = [], 0
    for line in lines[-limit:]:
        try:
            value = json.loads(line.decode('utf-8'))
            if not isinstance(value, dict):
                raise ValueError('CT log entry must be an object')
            rows.append(value)
        except (ValueError, TypeError):
            invalid += 1
    return dict(status='MEASURED', rows=rows, invalid_lines=invalid,
                truncated=position > 0 and len(lines) < limit)


def api_call(api_url: str, method: str, route: str, *, timeout: float = 10,
             payload: dict | None = None, params: dict | None = None,
             request_id: str | None = None) -> dict:
    if route not in ('/health', '/ready', '/api/search', '/api/recommend', '/api/event'):
        raise ValueError('unsupported dashboard API route')
    try:
        with requests.Session() as session:
            session.trust_env = False
            headers = {'X-Recommendation-Request-ID': request_id} if request_id else {}
            response = session.request(method, api_url + route, json=payload, params=params,
                                       headers=headers, timeout=timeout, allow_redirects=False)
        try:
            body = response.json()
        except ValueError:
            return dict(ok=False, status_code=response.status_code, data=None, error='API가 JSON 응답을 반환하지 않았습니다.')
        if response.ok:
            try:
                if not isinstance(body, dict):
                    raise ValueError('object expected')
                if route == '/api/search':
                    if body['search_type'] not in ('text', 'image', 'hybrid') or not isinstance(body['results'], list):
                        raise ValueError('invalid search schema')
                    float(body['latency_ms'])
                    int(body['total_count'])
                elif route == '/api/recommend':
                    if not isinstance(body['recommendations'], list):
                        raise ValueError('invalid recommendation schema')
                    float(body['pipeline_latency']['total_ms'])
                    body['session_context']['session_interest']
                elif route == '/api/event':
                    if type(body['applied']) is not bool:
                        raise ValueError('invalid event response')
                elif body['status'] != ('ok' if route == '/health' else 'ready'):
                    raise ValueError('invalid health/readiness schema')
            except (ValueError, KeyError, TypeError):
                return dict(ok=False, status_code=response.status_code, data=None, error='API 응답 형식이 계약과 다릅니다.')
        return dict(ok=response.ok, status_code=response.status_code, data=body,
                    request_id=response.headers.get('X-Recommendation-Request-ID'),
                    error=None if response.ok else f'API 요청 실패 (HTTP {response.status_code})')
    except requests.RequestException:
        return dict(ok=False, status_code=None, data=None, error='API에 연결할 수 없습니다. 서비스 실행과 API_URL을 확인하세요.')
