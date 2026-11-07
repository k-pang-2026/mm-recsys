"""실제 HTTP·Redis로 동료 평가의 폴백·탐색·다양성·신상품·세션을 검사합니다."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from urllib.parse import urlencode
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from docker.http import request
from docker.runtime import runtime_config
from src.common.artifacts import file_hash, write_json
from src.common.console import emit_json, log, run_cli
from src.common.schemas import RecommendResponse
from src.serving.feature_store import create_feature_store, RedisFeatureStore


def verify(cfg: dict, api: str) -> dict:
    root = Path(cfg['paths']['data_dir'])
    products = pd.read_parquet(root / 'products.parquet').set_index('product_id')
    users = pd.read_parquet(root / 'users.parquet').user_id.tolist()[:3]
    manifest = json.loads((root / 'split_manifest.json').read_text())
    now = pd.Timestamp(cfg['simulator']['reference_time'])
    responses = {}
    checks = {}
    store = create_feature_store(cfg)
    if not isinstance(store, RedisFeatureStore):
        raise ValueError('동료 평가 세션 검사는 실제 Redis 연결이 필요합니다.')
    try:
        for uid in users:
            body = request(api + '/api/recommend?' + urlencode(dict(user_id=uid, top_n=10)))
            rows = RecommendResponse.model_validate(body).recommendations
            cats = [products.loc[r.product_id, cfg['recommend']['reranking']['category_field']] for r in rows]
            checks[f'diversity_{uid}'] = all(not cats[i] == cats[i+1] == cats[i+2] for i in range(len(cats)-2))
            checks[f'exploration_{uid}'] = 1 <= sum(r.is_exploration for r in rows) <= 2
            checks[f'new_item_{uid}'] = any(now-pd.Timedelta(days=7) <= products.loc[r.product_id, 'created_at'] <= now for r in rows)
            responses[uid] = body
        uid = 'peer-' + uuid.uuid4().hex
        before = request(api + '/api/recommend?' + urlencode(dict(user_id=uid, top_n=10)))
        checks['cold_start_0'] = any('인기·최근 상승 상품' == r['reason'] for r in before['recommendations'])
        pid = before['recommendations'][0]['product_id']
        event = dict(event_id=uuid.uuid4().hex, user_id=uid, product_id=pid, category=products.loc[pid, 'category_l3'], event_type='view', session_id='peer-review')
        applied = request(api + '/api/event', event)
        duplicated = request(api + '/api/event', event)
        after = request(api + '/api/recommend?' + urlencode(dict(user_id=uid, top_n=10)))
        features = store.get_features(uid)
        checks['event_deduplication'] = applied['applied'] and not duplicated['applied']
        checks['session_http'] = pid in after['session_context']['recent_clicks'] and after['session_context']['session_interest'] == event['category']
        checks['session_redis'] = pid in features.recent_clicks
        for _ in range(3):
            event = dict(event, event_id=uuid.uuid4().hex)
            request(api + '/api/event', event)
        four = request(api + '/api/recommend?' + urlencode(dict(user_id=uid, top_n=10)))
        checks['cold_start_4'] = any('인기·최근 상승 상품' == r['reason'] for r in four['recommendations'])
        responses['session'] = dict(before=before, event=event, applied=applied, duplicate=duplicated, after=after, four_events=four, redis=features.model_dump())
    finally:
        store.close()
    for name, passed in checks.items():
        label = next((label for prefix, label in [('diversity', '카테고리 다양성'),
            ('exploration', 'MAB 탐색 슬롯'), ('new_item', '신상품 노출'),
            ('cold_start', '신규 사용자 폴백'), ('event_deduplication', '이벤트 중복 방지'),
            ('session_http', 'HTTP 세션 반영'), ('session_redis', 'Redis 세션 저장')]
            if name.startswith(prefix)), name)
        log('동료 평가', label, f'{name}: ' + ('통과' if passed else '실패 / 다음 조치: 저장된 실제 응답과 정책 설정을 확인하세요.'), status='통과(PASS)' if passed else '실패(FAIL)')
    return dict(status='PASS' if all(checks.values()) else 'FAIL', acceptance='UNMEASURED',
        measured_at=datetime.now(timezone.utc).isoformat(), data_fingerprint=manifest['generation_fingerprint'],
        checks=checks, responses=responses, sources={str(p):file_hash(p) for p in (Path(__file__), Path('src/recommendation/reranking.py'))},
        scope='현재 HTTP·Redis 기능 실행; 품질·지연·A/B·CT·문서 종합 판정은 별도 요구사항 보고서')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-url', default='http://127.0.0.1:8000')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    cfg = runtime_config()
    result = verify(cfg, args.api_url.rstrip('/'))
    write_json(args.output or Path(cfg['paths']['results_dir']) / 'peer_review.json', result)
    emit_json(result)
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(run_cli(main, '동료 평가', 'API /ready·Redis 연결·실제 카테고리와 결과의 실패 항목을 확인하세요.'))
