"""Exercise the deployed HTTP/session/Redis bandit contract with real feedback."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import requests
from src.common.artifacts import file_hash, write_json
from src.common.config import load_config
from src.common.schemas import RecommendResponse
from src.serving.feature_store import RedisFeatureStore, create_feature_store


def verify(url: str, output: Path) -> dict:
    cfg = load_config()
    manifest = json.loads((Path(cfg['paths']['data_dir']) / 'split_manifest.json').read_text())
    store = create_feature_store(cfg)
    if not isinstance(store, RedisFeatureStore):
        raise ValueError('a real deployed Redis store is required')
    uid = 'integration-mab-' + uuid.uuid4().hex
    with requests.Session() as client:
        client.trust_env = False
        ready = client.get(url + '/ready', timeout=30)
        ready.raise_for_status()
        response = client.get(url + '/api/recommend', params={'user_id': uid, 'top_n': '10'}, timeout=60)
        response.raise_for_status()
        rec = RecommendResponse.model_validate(response.json())
        assert len(rec.recommendations) == 10
        headers = {'X-Recommendation-Request-ID': response.headers['X-Recommendation-Request-ID']}
        product = rec.recommendations[0].product_id
        before = store.arm_statistics([product])[store.arm_for(product)]
        payload = dict(event_id=uid + '-click', user_id=uid, product_id=product,
                       event_type='view', session_id=uid, category='integration-category')
        def feedback(body: dict) -> dict:
            reply = client.post(url + '/api/feedback', json=body, headers=headers, timeout=30)
            reply.raise_for_status()
            return reply.json()
        assert feedback(payload)['applied'] is True
        assert feedback(payload)['applied'] is False
        click = store.arm_statistics([product])[store.arm_for(product)]
        assert abs(click['reward'] - before['reward'] - cfg['recommend']['mab']['click_reward']) < 1e-8
        purchase = dict(payload, event_id=uid + '-purchase', event_type='purchase')
        assert feedback(purchase)['applied'] is True
        bought = store.arm_statistics([product])[store.arm_for(product)]
        assert abs(bought['reward'] - before['reward'] - cfg['recommend']['mab']['purchase_reward']) < 1e-8
        assert feedback(dict(payload, event_id=uid + '-late-click'))['applied'] is True
        assert store.arm_statistics([product])[store.arm_for(product)] == bought
        ids = [r.product_id for r in rec.recommendations[:3]]
        for index, pid in enumerate(ids):
            body = dict(payload, product_id=pid, event_id=f'{uid}-session-{index}')
            reply = client.post(url + '/api/event', json=body, timeout=30)
            reply.raise_for_status()
            assert reply.json()['applied'] is True
        after = client.get(url + '/api/recommend', params={'user_id': uid, 'top_n': '10'}, timeout=60)
        after.raise_for_status()
        session = RecommendResponse.model_validate(after.json()).session_context
        assert session.recent_clicks == ids and session.session_interest
    report = dict(status='PASS', scale=cfg['scale'], data_fingerprint=manifest['generation_fingerprint'],
        checks={'live_redis_mab': 'PASS', 'dedup_feedback': 'PASS', 'max_reward': 'PASS', 'session_response': 'PASS',
                'unknown_user': 'PASS', 'request_attribution_header': 'PASS'},
        reward_before=before, reward_click=click, reward_purchase=bought,
        session=session.model_dump(), url=url, source_hashes={name: file_hash(Path(name)) for name in
            ['src/serving/feature_store.py', 'src/recommendation/recommender.py', 'scripts/verify_integration_mab.py']},
        scope='real deployed HTTP + separate Redis client observation; latest user/product exposure attribution, no quality-lift claim')
    write_json(output, report)
    store.close()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-url', default='http://127.0.0.1:8000')
    parser.add_argument('--output', type=Path, default=Path('docs/results/integration/mab_full.json'))
    args = parser.parse_args()
    result = verify(args.api_url.rstrip('/'), args.output)
    print(f"HTTP/Redis MAB {result['status']}: {args.output}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
