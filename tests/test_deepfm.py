import pandas as pd
import numpy as np
import pytest
import torch

from src.recommendation.deepfm import DeepFM, loss
from src.recommendation.ranking_labels import build_labels
from src.recommendation.bundle_compat import validate_candidate_config
from src.common.artifacts import fingerprint


def fixture():
    at=pd.Timestamp('2026-01-01T00:00:00Z')
    imps=pd.DataFrame([dict(impression_id=f'i{i}',request_id=f'r{i}',user_id='u',product_id='p',exposed_at=at+pd.Timedelta(minutes=i*10),position=1) for i in range(4)])
    events=pd.DataFrame([dict(event_id='v0',user_id='u',product_id='p',session_id='s',timestamp=at,event_type='view',impression_id='i0'),
                         dict(event_id='v1',user_id='u',product_id='p',session_id='s',timestamp=at+pd.Timedelta(minutes=10),event_type='view',impression_id='i1'),
                         dict(event_id='p1',user_id='u',product_id='p',session_id='s',timestamp=at+pd.Timedelta(minutes=12),event_type='purchase',impression_id=None),
                         dict(event_id='p2',user_id='u',product_id='p',session_id='other',timestamp=at+pd.Timedelta(minutes=15),event_type='purchase',impression_id=None)])
    return at,imps,events


def test_attribution_latest_session_censor_and_boundary():
    at,imps,events=fixture(); labels,stats=build_labels(imps,events,at,at+pd.Timedelta(minutes=35),1800)
    assert labels.ctr.tolist()==[1,1,0,0]
    assert labels.cvr.tolist()==[0,1,0,0]
    assert labels.cvr_mask.tolist()==[True,True,False,False]
    assert labels.ctr_mask.tolist()==[True,True,False,False]
    assert stats['unassigned_purchases']==1 and stats['censored']==3
    # Future conversion outside observation end cannot create a label.
    labels,_=build_labels(imps,events,at,at+pd.Timedelta(minutes=11),1800)
    assert labels.cvr.sum()==0 and not labels.cvr_mask.any()


def test_label_duplicate_and_window():
    at,imps,events=fixture()
    with pytest.raises(ValueError,match='duplicate'): build_labels(pd.concat([imps,imps]),events,at,at,1800)
    labels,_=build_labels(imps,events,at,at+pd.Timedelta(hours=2),30)
    assert labels.cvr.sum()==0


def test_deepfm_fm_linear_dnn_and_conditional_gradients():
    torch.manual_seed(4); model=DeepFM([4,5],3,dict(embedding_dim=4,hidden_dims=[8,4]))
    logits=model(torch.tensor([[1,2],[2,3]]),torch.ones(2,3))
    assert logits.shape==(2,2)
    masks=torch.tensor([[1.,0.],[1.,1.]])
    value=loss(logits,torch.tensor([[1.,0.],[0.,1.]]),masks,1.)
    value.backward()
    assert all(p.grad is not None and torch.isfinite(p.grad).all() for p in model.parameters())
    logits=torch.zeros(2,2,requires_grad=True); loss(logits,torch.ones(2,2),masks,1.).backward()
    assert logits.grad[0,1]==0 and logits.grad[1,1]!=0


def test_candidate_config_snapshot_fail_closed(tmp_path):
    import json
    original=dict(candidate={'dim':64},candidate_k=300,exclude_purchased=False,evaluation={},baselines={},diagnostics={})
    path=tmp_path/'snapshot.json'; path.write_text(json.dumps(original))
    cfg={'recommend':dict(original,candidate_config_snapshot=str(path),ranking={'epochs':20})}
    meta={'config_fingerprint':fingerprint(original)}
    validate_candidate_config(meta,cfg)
    cfg['recommend']['candidate']={'dim':128}
    with pytest.raises(ValueError,match='scope'): validate_candidate_config(meta,cfg)
    path.write_text('{}')
    with pytest.raises(ValueError,match='checksum'): validate_candidate_config(meta,cfg)


def test_ranking_history_strict_timestamp_and_excluded_columns():
    from src.recommendation.features import FeatureEncoder, ITEM_FIELDS
    from src.recommendation.ranking_features import HistoryIndex,RankingEncoder,DENSE_FIELDS
    at=pd.Timestamp('2025-01-01T00:00:00Z')
    products=pd.DataFrame(dict(product_id=['p','q'],price=[100,200],created_at=[at,at]))
    for field in ITEM_FIELDS: products[field]=['a','b']
    users=pd.DataFrame(dict(user_id=['u'],age_group=['18-24'],gender=['F'],signup_at=[at],persona=['secret']))
    events=pd.DataFrame(dict(event_id=['e','f'],user_id=['u','u'],product_id=['p','q'],timestamp=[at,at+pd.Timedelta(seconds=1)],event_type=['view','purchase'],session_id=['s','s']))
    metadata=FeatureEncoder.fit(products,users,at+pd.Timedelta(days=1)); table=metadata.item_table(products)
    history=HistoryIndex(events,table)
    raw=history.raw('u',np.array([1,1,1]),np.array([at.value,at.value+10**9,at.value+2*10**9]))
    assert raw[:,2].tolist()==pytest.approx([0,np.log(2),np.log(3)])
    assert raw[0,3:10].sum()==0 and raw[1,3]==1 and raw[1,6]==0
    encoder=RankingEncoder(metadata,np.zeros(len(DENSE_FIELDS),np.float32),np.ones(len(DENSE_FIELDS),np.float32),True)
    frame=pd.DataFrame(dict(user_id=['u'],product_id=['p'],exposed_at=[at],position=[1],impression_id=['label'],event_type=['purchase']))
    first=encoder.transform(frame,users,table,history)
    frame['position']=99; frame['impression_id']='different'; frame['event_type']='view'; users['persona']='changed'
    second=encoder.transform(frame,users,table,history)
    assert all(np.array_equal(a,b) for a,b in zip(first,second))
    future=events.copy(); future.timestamp+=pd.Timedelta(days=10)
    frozen=HistoryIndex(pd.concat([events,future.assign(event_id=['g','h'])]),table)
    assert np.array_equal(history.raw('u',np.array([1]),np.array([at.value])),frozen.raw('u',np.array([1]),np.array([at.value])))


def test_new_candidate_bundle_uses_separate_scope_hash():
    from src.recommendation.bundle_compat import candidate_scope
    from src.common.config import load_config
    cfg=load_config(); cfg['recommend'].pop('candidate_config_snapshot')
    meta={'candidate_scope_fingerprint':fingerprint(candidate_scope(cfg['recommend']))}
    cfg['recommend']['ranking']['hidden_dims']=[64,32]
    validate_candidate_config(meta,cfg)
    cfg['recommend']['candidate']['dim']=128
    with pytest.raises(ValueError,match='scope'): validate_candidate_config(meta,cfg)


def test_measure_reports_single_class_cvr_without_claiming_auc():
    from src.recommendation.train_deepfm import measure
    values=dict(targets=torch.tensor([[0.,0.],[1.,0.],[1.,0.]]),
                masks=torch.tensor([[1.,0.],[1.,1.],[1.,1.]]))
    result=measure(values,np.array([[0.1,0.5],[0.8,0.2],[0.9,0.1]]))
    assert result['ctr']['auc']==1.
    assert result['cvr']['auc'] is None
    assert result['cvr']['auc_status']=='UNDEFINED_SINGLE_CLASS'
    assert result['cvr']['samples']==2 and result['cvr']['positives']==0


def test_classification_rejects_model_different_from_valid_selection():
    import copy
    from src.recommendation.eval_deepfm import validate_selection
    selection=dict(selection_split='valid',model_sha256='chosen',config_fingerprint='cfg',
                   best_epoch=11,selected_valid={'ctr':{'auc':0.9}})
    meta=dict(hashes={'deepfm.pt':'chosen'},config_fingerprint='cfg')
    training=dict(best_epoch=11,bundle=meta,selected_valid=selection['selected_valid'])
    validate_selection(selection,training,meta)
    for key,value in [('selection_split','test'),('model_sha256','different'),('best_epoch',12)]:
        changed=copy.deepcopy(selection); changed[key]=value
        with pytest.raises(ValueError,match='frozen valid selection'):
            validate_selection(changed,training,meta)
