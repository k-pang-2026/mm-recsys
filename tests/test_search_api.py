import base64
from io import BytesIO
from types import SimpleNamespace
from pathlib import Path
import pandas as pd
from PIL import Image
import pytest
from fastapi.testclient import TestClient

from src.common.config import load_config
from src.common.schemas import SearchRequest
from src.search.api import create_app
from src.search.index import SearchHit
from src.search.service import SearchService, create_service

pytest_plugins = ['src.search.testing']


class FixtureSearcher:
    def __init__(self):
        self.products = pd.DataFrame({'name': ['shirt'], 'price': [100.0]}, index=['P1'])
        self.calls = []
    def eligible_ids(self):
        return {'P1', 'P2', 'P3'}
    def search(self, text, image, k):
        mode = 'hybrid' if text and image else 'image' if image else 'text'
        self.calls.append((mode, k))
        if image:
            assert image.mode == 'RGB'
        return mode, [SearchHit('P1', 0.9)]


@pytest.fixture
def image_bytes():
    stream = BytesIO(); Image.new('L', (20, 20), 150).save(stream, format='PNG')
    return stream.getvalue()


def test_json_three_modes_share_response_contract(image_bytes):
    searcher = FixtureSearcher()
    with TestClient(create_app(search_service=SearchService(searcher))) as client:
        image = base64.b64encode(image_bytes).decode()
        for mode, payload in [('text', {'query_text': 'shirt'}), ('image', {'query_image': image}),
                              ('hybrid', {'query_text': '셔츠', 'query_image': 'data:image/png;base64,'+image})]:
            response = client.post('/api/search', json=payload)
            assert response.status_code == 200
            body = response.json()
            assert set(body) == {'search_type', 'results', 'latency_ms', 'total_count'}
            assert body['search_type'] == mode and body['total_count'] == 3
            assert body['results'][0]['product_id'] == 'P1'
            assert isinstance(body['latency_ms'], float) and body['latency_ms'] >= 0


@pytest.mark.parametrize('payload', [{}, {'query_text': ' '}, {'query_image': 'bad'},
    {'query_image': base64.b64encode(b'not an image').decode()},
    *[{'query_text': 'shirt', 'top_k': k} for k in (0, -1, 101, True, '10', 1.5)],
    {'query_text': 'shirt', 'extra': 'forbidden'}])
def test_invalid_json_fails_before_encoder_call(payload):
    searcher = FixtureSearcher()
    with TestClient(create_app(search_service=SearchService(searcher))) as client:
        assert client.post('/api/search', json=payload).status_code == 422
        assert searcher.calls == []


def test_multipart_image_hybrid_and_invalid_fields(image_bytes):
    with TestClient(create_app(search_service=SearchService(FixtureSearcher()))) as client:
        files = {'query_image': ('query.png', image_bytes, 'image/png')}
        assert client.post('/api/search', files=files).json()['search_type'] == 'image'
        response = client.post('/api/search', files=files, data={'query_text': 'shirt', 'top_k': '7'})
        assert response.status_code == 200 and response.json()['search_type'] == 'hybrid'
        assert client.post('/api/search', files=files, data={'top_k': '1.5'}).status_code == 422
        assert client.post('/api/search', files={'query_image': ('bad', b'bad')}).status_code == 422
        assert client.post('/api/search', files=files, data={'unknown': 'x'}).status_code == 422


def test_factory_is_loaded_once_per_lifespan(monkeypatch, tmp_path):
    import src.search.service as module
    cfg = load_config(); cfg['paths']['model_dir'] = str(tmp_path)
    (tmp_path/'search').mkdir(); (tmp_path/'search/indexes_current.json').write_text('{"fingerprint":"fixture"}')
    monkeypatch.delenv('SEARCH_MODEL_DIR', raising=False)
    calls = []
    monkeypatch.setattr(module, 'Searcher', lambda cfg: calls.append(cfg) or FixtureSearcher())
    with TestClient(create_app(cfg)) as client:
        for _ in range(3):
            assert client.post('/api/search', json={'query_text': 'shirt'}).status_code == 200
        assert client.get('/health').json()['search_ready']
    assert len(calls) == 1


def test_missing_model_and_corrupt_model_have_different_behavior(monkeypatch, tmp_path):
    cfg = load_config(); cfg['paths']['model_dir'] = str(tmp_path)
    monkeypatch.delenv('SEARCH_MODEL_DIR', raising=False)
    assert create_service(cfg) is None
    (tmp_path/'search').mkdir(); (tmp_path/'search/indexes_current.json').write_text('bad JSON')
    with pytest.raises(ValueError):
        create_service(cfg)


def test_total_count_means_catalog_not_response_length():
    result = SearchService(FixtureSearcher()).search(SearchRequest(query_text='shirt'))
    assert result.total_count == 3 and len(result.results) == 1
