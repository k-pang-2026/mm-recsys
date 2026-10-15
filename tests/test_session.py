import numpy as np
import pandas as pd
import pytest
import torch
from fastapi.testclient import TestClient

from src.recommendation.testing import service_fixture
from src.recommendation.feature_store import RecommendationFeatureStore
from src.recommendation.service import create_service
from src.recommendation.session import sequence_for
from src.recommendation.train_session import examples
from src.serving.main import create_app


def test_shared_api_three_clicks_interest_recommendation_and_feedback(tmp_path,monkeypatch):
    monkeypatch.delenv('RECOMMEND_MODEL_DIR',raising=False)
    cfg,data=service_fixture(tmp_path); cfg['recommend']['mab']['epsilon']=0.
    store=RecommendationFeatureStore(cfg,data['products'])
    service=create_service(cfg,store)
    before_vector=service.candidate.user_vectors([service.context('u',[])])
    with TestClient(create_app(cfg,recommend_service=service,feature_store=store)) as client:
        before=client.get('/api/recommend',params={'user_id':'u','top_n':10}).json()
        for i in range(3):
            payload=dict(event_id=f'click{i}',user_id='u',product_id='p04',event_type='view',session_id='new')
            assert client.post('/api/event',json=payload).json()['applied']
        features=store.get_features('u'); assert features.recent_clicks==['p04']*3
        after=client.get('/api/recommend',params={'user_id':'u','top_n':10}).json()
        assert after['session_context']['session_interest']=='category_l3-4'
        assert [x['product_id'] for x in before['recommendations']]!=[x['product_id'] for x in after['recommendations']]
        long=service.candidate.user_vectors([service.context('u',features.recent_clicks)])
        combined=service.session_model.combine(long,sequence_for(features.recent_clicks,service.table,20),cfg['recommend']['session'])
        assert not np.allclose(before_vector,combined) and np.linalg.norm(combined)==pytest.approx(1.,abs=1e-5)
        product=after['recommendations'][0]['product_id']; stats=store.arm_statistics()[product].copy()
        payload=dict(event_id='reward',user_id='u',product_id=product,event_type='purchase')
        assert client.post('/api/feedback',json=payload).json()['applied']
        assert not client.post('/api/feedback',json=payload).json()['applied']
        assert store.arm_statistics()[product]['reward']==stats['reward']+1.


def test_session_examples_strict_times_and_reload_fixture(tmp_path,monkeypatch):
    monkeypatch.delenv('RECOMMEND_MODEL_DIR',raising=False)
    cfg,data=service_fixture(tmp_path); service=create_service(cfg,RecommendationFeatureStore(cfg,data['products']))
    seq,target,times,latest=examples(data['train'],service.table,20,data['train'].timestamp.min(),data['train'].timestamp.max())
    assert (latest<times).all() and len(seq)==5
    assert service.session_model(torch.zeros(1,20,dtype=torch.long)).abs().sum()==0
    assert np.array_equal(seq[0,:1],[service.table.id_to_index['p00']])
    assert np.isfinite(service.session_model(torch.from_numpy(seq)).detach().numpy()).all()
