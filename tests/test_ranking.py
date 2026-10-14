"""C-TEST-003: isolate missing/healthy/corrupt bundles from local artifacts."""
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from src.common.config import load_config
from src.common.schemas import RecommendResponse
from src.recommendation.testing import service_fixture
from src.recommendation.feature_store import RecommendationFeatureStore
from src.recommendation.service import create_service
from src.serving.main import create_app


def test_missing_model_is_503_independent_of_local_files(tmp_path,monkeypatch):
    monkeypatch.delenv('RECOMMEND_MODEL_DIR',raising=False)
    cfg=load_config(); cfg['paths']['model_dir']=str(tmp_path/'missing')
    store=RecommendationFeatureStore(cfg)
    assert create_service(cfg,store) is None
    with TestClient(create_app(cfg,feature_store=store)) as client:
        assert client.get('/api/recommend',params={'user_id':'new'}).status_code==503


def test_ready_model_schema_unknown_user_and_factory_shared_app(tmp_path,monkeypatch):
    monkeypatch.delenv('RECOMMEND_MODEL_DIR',raising=False)
    cfg,data=service_fixture(tmp_path); store=RecommendationFeatureStore(cfg,data['products'])
    with TestClient(create_app(cfg,feature_store=store)) as client:
        for user in ['u','new']:
            result=client.get('/api/recommend',params={'user_id':user,'top_n':10})
            assert result.status_code==200
            parsed=RecommendResponse.model_validate(result.json())
            assert len(parsed.recommendations)==10 and parsed.pipeline_latency.total_ms>0
            assert len(set(item.product_id for item in parsed.recommendations))==10
            if user=='new': assert any('인기' in item.reason for item in parsed.recommendations)
        assert client.get('/api/recommend',params={'user_id':'u','top_n':0}).status_code==422
        assert client.get('/api/recommend',params={'user_id':'u','top_n':101}).status_code==422
        assert sum(s['exposures'] for s in store.arm_statistics().values())==20


@pytest.mark.parametrize('name',['ranking/deepfm.pt','session/session.pt','two_tower.pt','item_index.faiss'])
def test_present_corrupted_model_fails_startup(tmp_path,monkeypatch,name):
    monkeypatch.delenv('RECOMMEND_MODEL_DIR',raising=False)
    cfg,data=service_fixture(tmp_path); path=Path(cfg['paths']['model_dir'])/'v1.0'/name
    path.write_bytes(path.read_bytes()+b'corrupted')
    with pytest.raises(ValueError,match='checksum'):
        create_service(cfg,RecommendationFeatureStore(cfg,data['products']))


def test_present_incomplete_bundle_fails(tmp_path,monkeypatch):
    monkeypatch.delenv('RECOMMEND_MODEL_DIR',raising=False)
    cfg,data=service_fixture(tmp_path); (Path(cfg['paths']['model_dir'])/'v1.0'/'ranking'/'features.json').unlink()
    with pytest.raises(ValueError,match='incomplete'):
        create_service(cfg,RecommendationFeatureStore(cfg,data['products']))


def test_prepared_candidate_missing_index_is_startup_error(tmp_path,monkeypatch):
    monkeypatch.delenv('RECOMMEND_MODEL_DIR',raising=False)
    cfg,data=service_fixture(tmp_path)
    (Path(cfg['paths']['model_dir'])/'v1.0'/'index_manifest.json').unlink()
    with pytest.raises(ValueError,match='incomplete'):
        create_service(cfg,RecommendationFeatureStore(cfg,data['products']))
