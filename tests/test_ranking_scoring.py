import copy
import numpy as np
import pytest
from fastapi.testclient import TestClient
from src.recommendation.scoring import score_items, policy
from src.recommendation.testing import service_fixture
from src.recommendation.feature_store import RecommendationFeatureStore
from src.serving.main import create_app


def test_legacy_product_ctr_and_fusion_formula():
    ids=['b','a','c']; p=np.array([[.3,.9],[.8,.1],[.5,.4]],dtype=np.float32)
    assert np.allclose([x.score for x in score_items(ids,p)],p[:,0]*p[:,1])
    assert [x.score for x in score_items(ids,p,{'strategy':'ctr'})]==pytest.approx(p[:,0])
    for alpha in [.25,.5,.75]:
        result=score_items(ids,p,{'strategy':'rank_fusion','alpha':alpha})
        assert [x.score for x in result]==pytest.approx([(1-alpha),.5*(1-alpha)+alpha,.5*alpha])
    tied=score_items(['z','a'],np.ones((2,2)),{'strategy':'rank_fusion','alpha':1.})
    assert sorted(tied,key=lambda x:(-x.score,x.product_id))[0].product_id=='a'


@pytest.mark.parametrize('spec',[{'strategy':'ctr_cvr'},{'strategy':'ctr'},{'strategy':'rank_fusion','alpha':.25}])
def test_empty_singleton_and_api_evaluation_agree(tmp_path,monkeypatch,spec):
    monkeypatch.delenv('RECOMMEND_MODEL_DIR',raising=False)
    assert score_items([],np.empty((0,2)),spec)==[]
    item=score_items(['p'],np.array([[.8,.2]]),spec)[0]
    assert item.score==pytest.approx(1. if spec['strategy']=='rank_fusion' else .8 if spec['strategy']=='ctr' else .16)
    cfg,data=service_fixture(tmp_path);cfg['recommend']['scoring']=spec
    cfg['recommend']['enable_reranking']=False
    with TestClient(create_app(cfg,feature_store=RecommendationFeatureStore(cfg,data['products']))) as client:
        service=client.app.state.recommend
        import torch
        with torch.inference_mode():
            features=service.store.get_features('u'); context=service.context('u',features.recent_clicks)
            products=service.candidate_products(context,features)
            predictions=service.predict_products('u',products,features)
        expected=sorted(score_items(products,predictions,spec),key=lambda x:(-x.score,x.product_id))[:10]
        response=client.get('/api/recommend',params={'user_id':'u','top_n':10}).json()
        assert [x['product_id'] for x in response['recommendations']]==[x.product_id for x in expected]
        assert [x['score'] for x in response['recommendations']]==pytest.approx([x.score for x in expected])


@pytest.mark.parametrize('bad',[np.nan,np.inf,-np.inf,-.1,1.1])
def test_invalid_values_rejected(bad):
    with pytest.raises(ValueError): score_items(['p'],np.array([[bad,.5]]))


def test_invalid_policy_shape_duplicates():
    for spec in [{'strategy':'other'},{'strategy':'rank_fusion','alpha':np.nan},{'strategy':'rank_fusion','alpha':2}]:
        with pytest.raises(ValueError): policy(spec)
    with pytest.raises(ValueError): score_items(['a'],np.ones((1,)))
    with pytest.raises(ValueError): score_items(['a','a'],np.ones((2,2)))


def test_selection_eligibility_and_deterministic_ties():
    from src.recommendation.eval_policy import choose
    def row(name,ndcg,hit=.3,cov=.4,ok=True,operational=True):
        return dict(name=name,operational=operational,metrics=dict(ndcg_at_50=ndcg,hit_rate_at_50=hit,coverage=cov),checks=dict(quality=ok))
    assert choose([row('baseline',.9,operational=False),row('failed',.8,ok=False)]) is None
    assert choose([row('first',.1),row('second',.1)])['name']=='first'
    assert choose([row('first',.1),row('second',.1,hit=.4)])['name']=='second'
    assert choose([row('first',.1),row('second',.2)])['name']=='second'


def test_policy_stores_rng_and_configuration_are_independent(tmp_path):
    from src.recommendation.eval_policy import isolated_policy
    from src.recommendation.service import create_service
    cfg,data=service_fixture(tmp_path)
    base=create_service(cfg,RecommendationFeatureStore(cfg,data['products']))
    a=isolated_policy(base,{'strategy':'ctr'});b=isolated_policy(base,{'strategy':'rank_fusion','alpha':.25})
    a.store.record_exposures('u',['p00']);a.cfg['recommend']['mab']['epsilon']=.9
    a.rng.random(30)
    assert b.store.arm_statistics()=={} and base.store.arm_statistics()=={}
    assert b.cfg['recommend']['mab']['epsilon']==0 and base.cfg['recommend']['mab']['epsilon']==0
    assert b.rng.random()==np.random.default_rng(cfg['seed']+20).random()
    assert a.candidate is b.candidate and a.ranker is b.ranker


@pytest.mark.parametrize('algo',['epsilon_greedy','ucb'])
def test_b5_api_and_offline_pipeline_same_input_and_state(tmp_path,monkeypatch,algo):
    from src.recommendation.eval_policy import isolated_policy
    monkeypatch.delenv('RECOMMEND_MODEL_DIR',raising=False)
    cfg,data=service_fixture(tmp_path);cfg['recommend']['scoring']={'strategy':'ctr'}
    cfg['recommend']['mab']['algo']=algo
    with TestClient(create_app(cfg,feature_store=RecommendationFeatureStore(cfg,data['products']))) as client:
        service=client.app.state.recommend;offline=isolated_policy(service,cfg['recommend']['scoring'])
        import torch
        with torch.inference_mode():
            features=offline.store.get_features('u');context=offline.context('u',features.recent_clicks)
            products=offline.candidate_products(context,features)
            predictions=offline.predict_products('u',products,features)
            expected,diag=offline.rerank_items(offline.rank_products(products,predictions),10,context)
        assert diag['violations']==[]
        actual=client.get('/api/recommend',params={'user_id':'u','top_n':10}).json()['recommendations']
        assert [(x['product_id'],x['is_exploration'],x['reason']) for x in actual]==[(x.product_id,x.is_exploration,x.reason) for x in expected]
        assert [x['score'] for x in actual]==pytest.approx([x.score for x in expected])


def test_models_are_loaded_once_at_lifespan(tmp_path,monkeypatch):
    import src.recommendation.service as factory
    monkeypatch.delenv('RECOMMEND_MODEL_DIR',raising=False)
    cfg,data=service_fixture(tmp_path);original=factory.load_ranking;calls=[]
    def counted(*args):
        calls.append(True);return original(*args)
    monkeypatch.setattr(factory,'load_ranking',counted)
    with TestClient(create_app(cfg,feature_store=RecommendationFeatureStore(cfg,data['products']))) as client:
        for n in [1,10,100]:
            assert client.get('/api/recommend',params={'user_id':'u','top_n':n}).status_code==200
    assert len(calls)==1


@pytest.mark.parametrize('split,result',[('valid',{'selection_status':'WITHHELD'}),('test',{'quality_status':'FAIL'})])
def test_quality_requirement_cli_exits_nonzero(monkeypatch,tmp_path,split,result):
    from src.recommendation import eval_policy
    monkeypatch.setattr(eval_policy,'evaluate',lambda *args:result)
    monkeypatch.setattr(eval_policy,'load_config',lambda:{'scale':'full','paths':{'results_dir':str(tmp_path)}})
    monkeypatch.setattr('sys.argv',['eval_policy','--split',split,'--require-quality'])
    assert eval_policy.main()==1
    monkeypatch.setattr('sys.argv',['eval_policy','--split',split])
    assert eval_policy.main()==0


def test_feasible_constraint_miss_excludes_otherwise_eligible_policy():
    from src.common.config import load_config
    from src.recommendation.eval_policy import quality_checks,choose
    cfg=load_config();metrics={k:cfg['targets'][k] for k in ['hit_rate_at_50','ndcg_at_50','coverage']}
    checks=quality_checks(metrics,cfg,1)
    assert checks['hit_rate_at_50'] and checks['ndcg_at_50'] and checks['coverage']
    assert not checks['feasible_pool_constraints']
    assert choose([dict(name='invalid',operational=True,metrics=metrics,checks=checks)]) is None


def test_implementation_pass_does_not_mask_quality_failure_in_verifier(monkeypatch,tmp_path):
    from src.recommendation import verify_ranking,verify_policy
    cfg={'scale':'full','paths':{'results_dir':str(tmp_path)}}
    (tmp_path/'ranking_policy_selection_full.json').write_text('{}')
    report=dict(status='PASS',implementation='PASS',recommendation_quality='FAIL',environment={'asgi':'PASS','tcp':'UNMEASURED'})
    monkeypatch.setattr(verify_ranking,'load_config',lambda:cfg)
    monkeypatch.setattr(verify_policy,'verify',lambda _:report)
    monkeypatch.setattr('sys.argv',['verify_ranking','--write','--require-quality'])
    assert verify_ranking.main()==1
