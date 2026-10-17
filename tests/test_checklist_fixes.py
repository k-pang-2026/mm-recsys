from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from src.common.config import load_config
from src.common.schemas import UserFeatures
from src.recommendation.feature_store import RecommendationFeatureStore
from src.recommendation.recommender import Recommender
from src.recommendation.reranking import Reranker, diversity_capacity
from src.recommendation.scoring import score_items
from src.recommendation.testing import service_fixture
from src.serving.main import create_app


def serving_pool(history_count=0):
    cfg=load_config(); cfg['recommend']['exclude_purchased']=True
    at=pd.Timestamp(cfg['simulator']['reference_time'])
    ids=[f'p{i:03}' for i in range(501)]
    products=pd.DataFrame(dict(product_id=ids,
        category_l3=['a' if i<=400 else 'b' for i in range(501)],
        created_at=[at-pd.Timedelta(days=30)]*501))
    products.loc[400,'created_at']=at-pd.Timedelta(days=1)
    products.loc[499,'created_at']=at
    products.loc[500,'created_at']=at+pd.Timedelta(days=1)
    service=object.__new__(Recommender)
    service.cfg=cfg;service.at=at;service.scoring={'strategy':'ctr'}
    service.session_model=None
    service.reranker=Reranker(cfg,products)
    service.fallback_sorted=ids
    service.fallback_scores={p:1. for p in ids}
    service.catalog_by_recency=sorted(ids,key=lambda p:(-service.reranker.created[p].value,p))
    service.table=SimpleNamespace(id_to_index={p:i+1 for i,p in enumerate(ids)})
    service.candidate=SimpleNamespace(allowed=set(range(1,501)),
        user_vectors=lambda contexts:np.zeros((1,2)),search=lambda *args:[ids[:300]])
    context=SimpleNamespace(history_count=history_count,purchased=frozenset({500}))
    return service,context


@pytest.mark.parametrize('history_count',[0,20])
def test_new_item_is_reserved_before_diversity_repair(history_count):
    from collections import Counter
    service,context=serving_pool(history_count)
    products=service.candidate_products(context,UserFeatures(),50)
    assert len(products)==len(set(products))==300
    assert 'p400' in products and not {'p499','p500'}&set(products)
    assert diversity_capacity(Counter(service.reranker.categories[p] for p in products),2)>=50
    items=score_items(products,np.full((len(products),2),.5),{'strategy':'ctr'})
    result,diag=service.reranker.run(items,50,service.at,history_count,
        service.fallback_scores,{},lambda p:p,np.random.default_rng(42))
    assert 'p400' in {p.product_id for p in result}
    assert diag['status']=='PASS' and sum(x.is_exploration for x in result)==2


def test_no_available_new_item_and_disabled_reranking_keep_honest_pools():
    service,context=serving_pool()
    service.reranker.created['p400']=service.at-pd.Timedelta(days=8)
    products=service.candidate_products(context,UserFeatures(),10)
    assert not {'p400','p499','p500'}&set(products)
    service,context=serving_pool(20)
    service.cfg['recommend']['enable_reranking']=False
    assert service.candidate_products(context,UserFeatures())==service.fallback_sorted[:300]


@pytest.mark.parametrize('history_count',[0,20])
def test_newest_candidates_use_catalog_dates_and_observe_eligibility(history_count):
    service,context=serving_pool(history_count)
    service.scoring={'strategy':'newest'}
    service.cfg['recommend']['enable_reranking']=False
    products=service.candidate_products(context,UserFeatures())
    assert products[0]=='p400' and len(products)==300
    assert not {'p499','p500'}&set(products)


def test_newest_timestamps_ties_and_similarity_order():
    ids=['older','z','a'];at=pd.Timestamp('2026-01-01',tz='UTC')
    dates={'older':at-pd.Timedelta(days=1),'z':at,'a':at}
    probabilities=np.array([[.9,.9],[.5,.5],[.1,.1]])
    newest=score_items(ids,probabilities,{'strategy':'newest'},created_at=dates)
    assert [x.product_id for x in sorted(newest,key=lambda x:(-x.score,x.product_id))]==['a','z','older']
    similarity=score_items(ids,probabilities[::-1],{'strategy':'similarity'})
    assert [x.product_id for x in sorted(similarity,key=lambda x:-x.score)]==ids
    assert score_items([],np.empty((0,2)),{'strategy':'newest'})==[]
    for bad in [None,{'older':at,'z':pd.NaT,'a':at}]:
        with pytest.raises(ValueError,match='registration timestamps'):
            score_items(ids,probabilities,{'strategy':'newest'},created_at=bad)


def test_newest_diversity_refill_prefers_recent_alternative():
    service,context=serving_pool()
    service.scoring={'strategy':'newest'}
    for pid in service.reranker.created:
        service.reranker.created[pid]=service.at-pd.Timedelta(days=1 if int(pid[1:])<=400 else 4)
    service.reranker.created['p402']=service.at-pd.Timedelta(days=2)
    service.catalog_by_recency=sorted(service.reranker.created,key=lambda p:(-service.reranker.created[p].value,p))
    products=service.candidate_products(context,UserFeatures(),3)
    assert 'p402' in products and 'p401' not in products


def test_newest_survives_cold_fallback_with_mab_and_diversity():
    service,context=serving_pool()
    service.cfg['recommend']['scoring']={'strategy':'newest'}
    service.scoring={'strategy':'newest'}
    products=service.candidate_products(context,UserFeatures(),10)
    items=service.rank_products(products,np.full((len(products),2),.5))
    before={p.product_id:p.score for p in items}
    result,diag=service.reranker.run(items,10,service.at,0,
        {p.product_id:1000. for p in items},{},lambda p:p,np.random.default_rng(42))
    assert diag['status']=='PASS'
    assert all(p.score==before[p.product_id] for p in result)
    assert 'p400' in {p.product_id for p in result}
    assert any(p.reason=='등록일 최신순' for p in result)


@pytest.mark.parametrize('strategy',['newest','similarity'])
def test_api_accepts_configured_sorting_strategy(tmp_path,monkeypatch,strategy):
    monkeypatch.delenv('RECOMMEND_MODEL_DIR',raising=False)
    cfg,data=service_fixture(tmp_path)
    cfg['recommend']['scoring']={'strategy':strategy}
    cfg['recommend']['enable_reranking']=False
    with TestClient(create_app(cfg,feature_store=RecommendationFeatureStore(cfg,data['products']))) as client:
        response=client.get('/api/recommend',params={'user_id':'new-user','top_n':10})
        assert response.status_code==200
        rows=response.json()['recommendations']
        assert len(rows)==10
        assert all(('등록일' if strategy=='newest' else '유사도') in p['reason'] for p in rows)
        if strategy=='newest':
            assert [p['product_id'] for p in rows]==[f'p{i:02}' for i in range(10)]


def test_registered_model_restart_and_reload_keep_runtime_sorting(tmp_path,monkeypatch):
    import copy
    from starlette.requests import Request
    from src.ct.bootstrap import bootstrap
    from src.ct.retrain_trigger import components
    from src.serving.ct_admin import ReloadRequest,reload_model
    monkeypatch.delenv('RECOMMEND_MODEL_DIR',raising=False)
    cfg,data=service_fixture(tmp_path)
    cfg['paths']['results_dir']=str(tmp_path/'results')
    bootstrap(cfg)
    registry=components(cfg)[2];before=registry.read()
    runtime=copy.deepcopy(cfg);runtime['recommend']['scoring']={'strategy':'newest'}
    app=create_app(runtime,search_service=object(),feature_store=RecommendationFeatureStore(runtime,data['products']))
    with TestClient(app) as client:
        assert app.state.recommend.scoring=={'strategy':'newest'}
        assert client.get('/api/recommend',params={'user_id':'cold','top_n':10}).status_code==200
        request=Request({'type':'http','client':('127.0.0.1',5000),'app':app,'headers':[]})
        assert reload_model(ReloadRequest(),request)['version']=='v1.0'
        assert app.state.recommend.scoring=={'strategy':'newest'}
        assert app.state.recommend.reranker.spec['scoring']=={'strategy':'newest'}
    assert registry.read()==before


def test_docker_warmup_allows_sorting_but_rejects_model_config_changes(tmp_path,monkeypatch):
    import copy
    import fakeredis
    from scripts.prepare_all import stage
    from src.ct.bootstrap import bootstrap
    from src.serving import feature_store,warmup_features
    cfg,_=service_fixture(tmp_path)
    cfg['paths']['results_dir']=str(tmp_path/'results')
    bootstrap(cfg)
    monkeypatch.setattr(feature_store,'create_feature_store',lambda cfg:
        feature_store.RedisFeatureStore(fakeredis.FakeRedis(decode_responses=True)))
    monkeypatch.setattr(warmup_features,'warmup',lambda cfg,store:{'status':'PASS'})
    runtime=copy.deepcopy(cfg);runtime['recommend']['scoring']={'strategy':'newest'}
    stage(runtime,'warmup')
    runtime['recommend']['ranking']['hidden_dims']=[999]
    with pytest.raises(ValueError,match='different recommendation configuration'):
        stage(runtime,'warmup')


def test_ct_compares_models_under_the_same_runtime_policy(tmp_path,monkeypatch):
    import copy,shutil
    from pathlib import Path
    from src.ct import training
    from src.ct.bootstrap import bootstrap
    from src.ct.retrain_trigger import build_from_journal,components
    cfg,data=service_fixture(tmp_path);cfg['paths']['results_dir']=str(tmp_path/'results')
    source=Path(cfg['paths']['data_dir'])
    pd.concat([data['train'],data['valid']]).to_parquet(source/'events.parquet',index=False)
    pd.DataFrame(columns=['impression_id','request_id','user_id','product_id','exposed_at','position']).to_parquet(source/'impressions.parquet',index=False)
    bootstrap(cfg);registry=components(cfg)[2]
    runtime=copy.deepcopy(cfg);runtime['recommend']['scoring']={'strategy':'newest'}
    def snapshot(src,target,*args):
        shutil.copytree(src,target)
        return {'observed_through':cfg['simulator']['reference_time']}
    def train(local,work):
        bundle=work/'bundle';shutil.copytree(registry.root/'v1.0',bundle)
        (work/'results').mkdir()
        for name in ['candidate_training','ranking_training','session_training']:
            (work/'results'/f'{name}_{cfg["scale"]}.json').write_text('{}')
        return {},bundle
    seen=[]
    def validate(service,local):
        seen.append(service.scoring)
        return {'validation_fingerprint':'same-observed-cohort','ctr_auc':.8}
    monkeypatch.setattr(training,'snapshot',snapshot)
    monkeypatch.setattr(training,'train_all',train)
    monkeypatch.setattr(training,'validation',validate)
    build_from_journal(runtime,'v1.1',0,registry)
    assert seen==[{'strategy':'newest'},{'strategy':'newest'}]
