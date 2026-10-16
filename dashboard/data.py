"""Dashboard I/O uses only standalone dashboard image dependencies."""
from __future__ import annotations

import json
import math
import os
import re
import base64
from collections import deque
from pathlib import Path

import requests
import yaml
from dotenv import dotenv_values

VERSION = 'evaluation-dashboard-v1'


def settings(root: Path) -> dict:
    path = Path(os.getenv('CONFIG_PATH', 'config.yaml'))
    path = path if path.is_absolute() else root / path
    cfg = yaml.safe_load(path.read_text(encoding='utf-8'))
    configured = Path(os.getenv('RESULTS_DIR', cfg['paths']['results_dir']))
    defaults = dotenv_values(root / '.env') if (root / '.env').is_file() else {}
    return dict(results_dir=configured if configured.is_absolute() else root / configured,
                api_url=(os.getenv('API_URL') or defaults.get('API_URL') or 'http://localhost:8000').rstrip('/'),
                api_timeout=float(os.getenv('DASHBOARD_API_TIMEOUT', '10')),
                scale=os.getenv('SCALE', cfg.get('scale', 'dev')))


def available_reports(root: Path) -> list[Path]:
    return sorted((p for p in root.glob('evaluation_*_*.json')
                   if re.fullmatch(r'evaluation_(dev|full)_(valid|test)\.json', p.name)), key=lambda p: p.name)


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


def ct_log(root: Path, limit: int = 100) -> dict:
    path = root / 'ct_log.jsonl'
    if not path.is_file():
        return dict(status='UNMEASURED', rows=[], invalid_lines=0)
    if path.stat().st_size > 10_000_000:
        return dict(status='UNMEASURED', rows=[], invalid_lines=0, reason='CT 로그가 10MB를 초과했습니다.')
    rows, invalid = [], 0
    with path.open(encoding='utf-8') as stream:
        for line in deque(stream, maxlen=limit):
            try:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError('CT log entry must be an object')
                rows.append(value)
            except (ValueError, TypeError):
                invalid += 1
    return dict(status='MEASURED', rows=rows, invalid_lines=invalid)


def api_call(api_url: str, method: str, route: str, *, timeout: float = 10,
             payload: dict | None = None, params: dict | None = None) -> dict:
    if route not in ('/health', '/ready', '/api/search', '/api/recommend'):
        raise ValueError('unsupported dashboard API route')
    try:
        with requests.Session() as session:
            session.trust_env = False
            response = session.request(method, api_url + route, json=payload, params=params, timeout=timeout, allow_redirects=False)
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
                elif body['status'] != ('ok' if route == '/health' else 'ready'):
                    raise ValueError('invalid health/readiness schema')
            except (ValueError, KeyError, TypeError):
                return dict(ok=False, status_code=response.status_code, data=None, error='API 응답 형식이 계약과 다릅니다.')
        return dict(ok=response.ok, status_code=response.status_code, data=body,
                    error=None if response.ok else f'API 요청 실패 (HTTP {response.status_code})')
    except requests.RequestException:
        return dict(ok=False, status_code=None, data=None, error='API에 연결할 수 없습니다. 서비스 실행과 API_URL을 확인하세요.')
