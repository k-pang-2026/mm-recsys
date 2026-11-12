import json
import threading
import time
from pathlib import Path

import httpx
import pandas as pd
import uvicorn

from src.common.artifacts import file_hash, write_json
from src.common.config import load_config
from src.common.schemas import SearchResponse
from src.serving.main import create_app
from scripts.verify_peer_review import verify

cfg = load_config()
root = Path(cfg['paths']['results_dir'])
data = Path(cfg['paths']['data_dir'])
products = pd.read_parquet(data / 'products.parquet').set_index('product_id')
bag = products[(products.color == 'brown') & (products.category_l2 == 'bags')].iloc[0]
image = (data / bag.image_path).read_bytes()
app = create_app(cfg)
server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=0, log_level='warning'))
thread = threading.Thread(target=server.run, daemon=True)
thread.start()
try:
    start = time.monotonic()
    while not server.started:
        if not thread.is_alive() or time.monotonic() - start > 120:
            raise RuntimeError('live API startup failed')
        time.sleep(.1)
    url = f'http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}'
    peer = verify(cfg, url)
    write_json(root / 'peer_review.json', peer)
    responses, checks = {}, {}
    with httpx.Client(base_url=url, timeout=30, trust_env=False) as client:
        for mode in ('text', 'image', 'hybrid'):
            if mode == 'text':
                response = client.post('/api/search', json={'query_text': '검정 오버핏 후드티', 'top_k': 10})
            else:
                response = client.post('/api/search', files={'query_image': ('brown-bag.jpg', image, 'image/jpeg')},
                                       data={'query_text': '가방'} if mode == 'hybrid' else {})
            response.raise_for_status()
            body = response.json()
            SearchResponse.model_validate(body)
            rows = products.loc[[row['product_id'] for row in body['results']]]
            matches = ((rows.color == 'black') & (rows.category_l3 == 'hoodie') & (rows['style'] == 'oversized')
                       if mode == 'text' else (rows.color == 'brown') & (rows.category_l2 == 'bags'))
            checks[mode + '_schema'] = body['search_type'] == mode and len(rows) == 10 and body['total_count'] == 50000
            checks[mode + '_semantics'] = bool(matches.all())
            responses[mode] = dict(response=body, matching_items=int(matches.sum()),
                                   catalog_attributes=rows[['color', 'style', 'category_l2', 'category_l3']].reset_index().to_dict('records'))
        checks['invalid_body_422'] = client.post('/api/search', json={}).status_code == 422
        checks['body_limit_413'] = client.post('/api/search', content=b'x' * (8*1024*1024+1),
                                              headers={'content-type': 'application/json'}).status_code == 413
    report = dict(status='PASS' if all(checks.values()) and peer['status'] == 'PASS' else 'FAIL',
                  scope='native localhost HTTP, real CLIP/Two-Tower/DeepFM/GRU and isolated Redis; synthetic catalog examples',
                  checks=checks, responses=responses, image_product_id=str(bag.name),
                  image_sha256=file_hash(data / bag.image_path), verifier_sha256=file_hash(Path(__file__)))
    write_json(root / 'pdf_examples.json', report)
    print(json.dumps(dict(status=report['status'], checks=checks), ensure_ascii=False))
    if report['status'] != 'PASS':
        raise SystemExit(1)
finally:
    server.should_exit = True
    thread.join(15)
    if thread.is_alive():
        raise RuntimeError('live API did not stop')
