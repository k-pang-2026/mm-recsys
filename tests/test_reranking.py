import copy
import numpy as np
import pandas as pd
import pytest

from src.common.config import load_config
from src.common.schemas import EventRequest,FeedbackRequest
from src.recommendation.feature_store import RecommendationFeatureStore
from src.recommendation.reranking import Reranker,RankedItem


def catalog(n=30,categories=5):
    at=pd.Timestamp('2026-01-01T00:00:00Z')
    return at,pd.DataFrame(dict(product_id=[f'p{i}' for i in range(n)],category_l3=[f'c{i%categories}' for i in range(n)],category_l2=[f'b{i%categories}' for i in range(n)],created_at=[at-pd.Timedelta(days=i%10) for i in range(n)]))


@pytest.mark.parametrize('algo',['epsilon_greedy','ucb'])
def test_100_randomized_cases_and_small_n(algo):
    cfg=load_config(); cfg['recommend']['mab']['algo']=algo
    at,products=catalog(); reranker=Reranker(cfg,products); rng=np.random.default_rng(42)
    for i in range(100):
        scores=rng.random(len(products)); items=[RankedItem(p,float(s)) for p,s in zip(products.product_id,scores)]
        rng.shuffle(items); n=int(rng.integers(1,31))
        result,diagnostics=reranker.run(items+[items[0]],n,at,0 if i%2 else 20,dict(zip(products.product_id,scores)),{},lambda p:p,rng)
        assert diagnostics['status']=='PASS',diagnostics
        assert len(result)==n and len(set(x.product_id for x in result))==n
        assert sum(x.is_exploration for x in result)==min(n,2)
        assert any(at-products.set_index('product_id').loc[x.product_id,'created_at']<=pd.Timedelta(days=7) for x in result)


def test_impossible_conditions_are_reported():
    cfg=load_config(); at,products=catalog(5,1)
    reranker=Reranker(cfg,products)
    result,diag=reranker.run([RankedItem(p,1.) for p in products.product_id],10,at,0,{}, {},lambda p:p,np.random.default_rng(42))
    assert len(result)==5 and diag['status']=='INFEASIBLE' and 'diversity' in diag['violations']
    assert 'insufficient_distinct_candidates' in diag['diagnostics']


def test_reward_max_idempotent_recent_user_attribution_and_ttl():
    cfg=load_config(); at,products=catalog(); now=[0.]
    store=RecommendationFeatureStore(cfg,products,clock=lambda:now[0])
    store.record_exposures('u',['p0','p0','p1'])
    def feedback(identifier,user='u',kind='view'):
        return FeedbackRequest(event_id=identifier,user_id=user,product_id='p0',event_type=kind)
    assert store.update_reward(feedback('x')) and not store.update_reward(feedback('x'))
    assert store.arm_statistics()['p0']==dict(exposures=1,reward=.2)
    store.update_reward(feedback('purchase',kind='purchase')); store.update_reward(feedback('click-again'))
    assert store.arm_statistics()['p0']['reward']==1.
    store.update_reward(feedback('wrong-user',user='other'))
    assert store.unattributed_feedback==1 and store.arm_statistics()['p0']['reward']==1.
    store.record_exposures('u',['p0']); store.update_reward(feedback('latest'))
    assert store.arm_statistics()['p0']==dict(exposures=2,reward=1.2)
    now[0]+=cfg['recommend']['mab']['exposure_ttl_seconds']
    store.update_reward(feedback('expired',kind='purchase'))
    assert store.unattributed_feedback==2 and store.arm_statistics()['p0']['reward']==1.2
    snapshot=store.arm_statistics(); snapshot['p0']['reward']=999
    assert store.arm_statistics()['p0']['reward']==1.2


def test_category_arm_and_session_reset():
    cfg=load_config(); cfg['recommend']['mab']['arm']='category'; at,products=catalog()
    now=[0.]; store=RecommendationFeatureStore(cfg,products,clock=lambda:now[0])
    store.record_exposures('u',['p0','p5']); assert store.arm_statistics()['c0']['exposures']==2
    for i in range(3): store.append_event(EventRequest(event_id=f'e{i}',user_id='u',product_id='p0',event_type='view',session_id='a'))
    assert store.get_features('u').session_interest=='c0' and store.get_features('u').session_clicks==3
    store.append_event(EventRequest(event_id='new',user_id='u',product_id='p1',event_type='view',session_id='b'))
    assert store.get_features('u').recent_clicks==['p1']
    now[0]+=cfg['serving']['session_ttl_seconds']; assert store.get_features('u').recent_clicks==[]


def test_new_and_exploration_quota_overlap_keeps_feasible_diversity():
    cfg=load_config(); cfg['recommend']['mab']['epsilon']=0.
    at=pd.Timestamp('2026-01-01T00:00:00Z')
    products=pd.DataFrame(dict(product_id=['a','b','new','other'],category_l3=['x','x','x','y'],
                               created_at=[at-pd.Timedelta(days=10)]*2+[at,at-pd.Timedelta(days=10)]))
    result,diag=Reranker(cfg,products).run([RankedItem(p,4-i) for i,p in enumerate(products.product_id)],3,at,10,{}, {},lambda p:p,np.random.default_rng(42))
    assert diag['status']=='PASS' and 'new' in [x.product_id for x in result] and 'other' in [x.product_id for x in result]
    assert sum(x.is_exploration for x in result)==2


def test_bandit_feedback_changes_exploitation_and_ucb_unseen_arm():
    from src.recommendation.mab import EpsilonGreedy,UCB
    rng=np.random.default_rng(42); items=['a','b','c']; stats={'a':dict(exposures=10,reward=0.),'b':dict(exposures=10,reward=1.)}
    assert EpsilonGreedy(0.).select(items,stats,lambda p:p,rng,1)==['b']
    assert UCB(1.4).select(items,stats,lambda p:p,rng,1)==['c']


def test_configured_pipeline_order_changes_bandit_candidate_order():
    cfg=load_config(); cfg['recommend']['mab']['epsilon']=0.
    at=pd.Timestamp('2026-01-01T00:00:00Z')
    products=pd.DataFrame(dict(product_id=['a','b','c'],category_l3=['x','y','z'],created_at=[at-pd.Timedelta(days=10)]*3))
    items=[RankedItem('a',10),RankedItem('b',9),RankedItem('c',8)]; fallback={'c':10,'a':1,'b':0}
    first,_=Reranker(cfg,products).run(items,2,at,0,fallback,{},lambda p:p,np.random.default_rng(1))
    cfg['recommend']['reranking']['pipeline']=['exploration','new_item','cold_start','diversity']
    second,_=Reranker(cfg,products).run(items,2,at,0,fallback,{},lambda p:p,np.random.default_rng(1))
    assert {x.product_id for x in first}=={'c','a'}
    assert {x.product_id for x in second}=={'a','b'}


def test_rare_required_new_item_is_reserved_without_consuming_separator_early():
    cfg=load_config(); cfg['recommend']['mab']['epsilon']=0.
    at=pd.Timestamp('2026-01-01T00:00:00Z')
    products=pd.DataFrame(dict(product_id=['a1','a2','a3','a4','new'],category_l3=['a']*4+['b'],created_at=[at-pd.Timedelta(days=10)]*4+[at]))
    items=[RankedItem(p,float(5-i)) for i,p in enumerate(products.product_id)]
    output,diag=Reranker(cfg,products).run(items,5,at,10,{}, {},lambda p:p,np.random.default_rng(1))
    assert diag['status']=='PASS' and [x.product_id for x in output][2]=='new'
    assert sum(x.is_exploration for x in output)==2


def test_completion_feasibility_matches_exhaustive_small_sequences():
    from itertools import product
    from collections import Counter
    from src.recommendation.reranking import completion_feasible
    for counts_tuple in product(range(4),repeat=3):
        counts=dict(zip('abc',counts_tuple)); total=sum(counts_tuple)
        for slots in range(min(6,total)+1):
            for tail,run in [(None,0),('a',1),('a',2)]:
                for required in [{},{'a':1},{'a':2},{'a':1,'b':1}]:
                    def brute(prefix,left,need):
                        if len(prefix)==slots: return all(v<=0 for v in need.values())
                        for category in 'abc':
                            if left.get(category,0)<=0: continue
                            previous=([tail]*run if tail else [])+prefix
                            if len(previous)>=2 and previous[-2:]==[category,category]: continue
                            nxt=dict(left); nxt[category]-=1; quota=dict(need); quota[category]=max(0,quota.get(category,0)-1)
                            if brute(prefix+[category],nxt,quota): return True
                        return False
                    expected=brute([],counts,required)
                    assert completion_feasible(counts,required,slots,2,tail,run)==expected,(counts,required,slots,tail,run)
