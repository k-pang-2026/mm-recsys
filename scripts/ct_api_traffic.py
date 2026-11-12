#!/usr/bin/env python3
"""실행 중인 추천 API에 귀속 가능한 합성 시연 트래픽을 전송합니다."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import time
from urllib import error, parse, request
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docker.http import wait_ready
from src.common.console import emit_json, log, run_cli


def send(opener, url: str, payload: dict | None = None, request_id: str | None = None,
         *, timeout: float = 30) -> tuple[dict, str | None]:
    headers = {'Content-Type': 'application/json'}
    if request_id:
        headers['X-Recommendation-Request-ID'] = request_id
    req = request.Request(url, data=None if payload is None else json.dumps(payload).encode(), headers=headers)
    # POST retries retain the event ID, session and attribution; GET creates a new exposure.
    attempts = 3 if payload is not None else 1
    for attempt in range(attempts):
        try:
            with opener.open(req, timeout=timeout) as response:
                return json.load(response), response.headers.get('X-Recommendation-Request-ID')
        except (OSError, error.URLError) as exc:
            if isinstance(exc, error.HTTPError) and exc.code not in (429, 502, 503, 504):
                raise
            if payload is None or attempt + 1 == attempts:
                raise
            log('CT 트래픽', '재시도', f"event_id={payload['event_id']} / 같은 요청으로 재시도합니다.")
            time.sleep(attempt + 1)
    raise AssertionError('unreachable')


def visit(opener, api: str, user: str, run_id: str, index: int, top_n: int, record) -> dict:
    query = parse.urlencode({'user_id': user, 'top_n': top_n})
    response, request_id = send(opener, f'{api}/api/recommend?{query}')
    items = response.get('recommendations', [])
    if not request_id or response.get('user_id') != user or not items:
        raise ValueError('추천 응답의 request ID, 사용자 또는 추천 상품이 없습니다. CT 활성 상태를 확인하세요.')
    if any(not isinstance(item.get('product_id'), str) or not item['product_id'] for item in items):
        raise ValueError('추천 응답의 상품 ID가 잘못되었습니다.')
    mode = ('no_click', 'click_only', 'click_purchase')[index % 3]
    record(dict(event='exposure', index=index, user_id=user, request_id=request_id,
                product_ids=[item['product_id'] for item in items], mode=mode))
    counts = dict(exposures=1, views=0, purchases=0)
    if mode == 'no_click':
        return counts
    product = items[(index // 3) % len(items)]['product_id']
    session = f'ct-api-demo-{run_id}-{index}'
    kinds = ['view', 'purchase'] if mode == 'click_purchase' else ['view']
    for kind in kinds:
        payload = dict(event_id=f'{session}-{kind}', session_id=session, user_id=user,
                       product_id=product, event_type=kind)
        endpoint = '/api/event' if kind == 'view' else '/api/feedback'
        record(dict(event='intent', endpoint=endpoint, request_id=request_id, payload=payload))
        result, _ = send(opener, api + endpoint, payload, request_id)
        if not isinstance(result.get('applied'), bool):
            raise ValueError(f'{endpoint}: applied가 없는 응답입니다. 저장된 intent를 확인하세요.')
        record(dict(event='ack', event_id=payload['event_id'], applied=result['applied']))
        counts['views' if kind == 'view' else 'purchases'] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-url', default=os.getenv('API_URL', 'http://127.0.0.1:8000'))
    parser.add_argument('--requests', type=int, default=3600, help='추천 요청 수; 0이면 Ctrl+C까지 계속')
    parser.add_argument('--interval', type=float, default=1, help='각 추천 흐름 사이 대기 시간(초)')
    parser.add_argument('--users', type=int, default=100, help='U000001부터 순환할 사용자 수(1~10000)')
    parser.add_argument('--top-n', type=int, default=50, help='추천 상품 수(2~100), 기본 50은 HitRate@50 관측용')
    parser.add_argument('--output', type=Path, help='새 JSONL 파일 경로; 기존 파일은 덮어쓰지 않음')
    args = parser.parse_args()
    if args.requests < 0 or not 1 <= args.users <= 10000 or not 2 <= args.top_n <= 100:
        parser.error('requests >= 0, users 1~10000, top-n 2~100 범위여야 합니다.')
    if not math.isfinite(args.interval) or args.interval <= 0:
        parser.error('interval은 유한한 양수여야 합니다.')
    api = args.api_url.rstrip('/')
    if parse.urlsplit(api).scheme not in ('http', 'https') or not parse.urlsplit(api).netloc:
        parser.error('api-url은 http(s) URL이어야 합니다.')
    run_id = uuid.uuid4().hex
    output = args.output or (Path(os.getenv('RUNTIME_RESULTS_DIR', 'docs/results/docker/runtime-v44')) /
                            os.getenv('SCALE', 'full') / f'ct_api_traffic_{run_id}.jsonl')
    output.parent.mkdir(parents=True, exist_ok=True)
    totals = dict(exposures=0, views=0, purchases=0)
    index = 0
    status, code = 'COMPLETED', 0
    with output.open('x', encoding='utf-8') as stream:
        def record(value: dict) -> None:
            stream.write(json.dumps(dict(run_id=run_id, recorded_at=time.time(), synthetic=True, **value),
                                    ensure_ascii=False, allow_nan=False) + '\n')
            stream.flush()

        record(dict(event='start', api=api, requests=args.requests, interval=args.interval,
                    users=args.users, top_n=args.top_n, quality='UNMEASURED'))
        log('CT 트래픽', '시작', f'합성 시연 데이터가 실제 서비스에 저장됩니다. / 기록={output}')
        log('CT 트래픽', '범위', '추천 → 비클릭/클릭/클릭 후 구매를 순환합니다. 학습·승격 성공을 보장하지 않습니다.')
        try:
            wait_ready(api, 120)
            opener = request.build_opener(request.ProxyHandler({}))
            while args.requests == 0 or index < args.requests:
                counts = visit(opener, api, f'U{index % args.users + 1:06d}', run_id, index, args.top_n, record)
                for key in totals:
                    totals[key] += counts[key]
                index += 1
                if index <= 3 or index % 100 == 0:
                    log('CT 트래픽', '진행', f"추천={totals['exposures']} / 클릭={totals['views']} / 구매={totals['purchases']}")
                if args.requests == 0 or index < args.requests:
                    time.sleep(args.interval)
        except KeyboardInterrupt:
            status, code = 'INTERRUPTED', 130
        except Exception as exc:
            status = 'FAILED'
            record(dict(event='error', index=index, detail=str(exc)))
            raise
        finally:
            record(dict(event='end', status=status, completed_visits=index, counts=totals))
            log('CT 트래픽', '기록', f'상태={status} / 완료 흐름={index} / 원본={output}')
    emit_json(dict(status=status, synthetic=True, completed_visits=index, counts=totals,
                   output=str(output), training='UNMEASURED'))
    return code


if __name__ == '__main__':
    raise SystemExit(run_cli(main, 'CT 트래픽', 'API /ready와 JSONL의 intent·ack를 확인하세요. 재실행은 새 트래픽입니다.'))
