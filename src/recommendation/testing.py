"""Small self-contained service fixture; tests never depend on local trained artifacts."""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd
import torch

from src.common.artifacts import file_hash,fingerprint,write_json
from src.common.config import load_config
from src.recommendation.features import FeatureEncoder,ITEM_FIELDS
from src.recommendation.two_tower import TwoTower
from src.recommendation.train_two_tower import save_bundle
from src.recommendation.index import build_index
from src.recommendation.ranking_features import RankingEncoder,DENSE_FIELDS
from src.recommendation.deepfm import DeepFM
from src.recommendation.session import SessionEncoder


def service_fixture(root: Path) -> tuple[dict,dict]:
    cfg=load_config(); cfg['paths']['data_dir']=str(root/'data'); cfg['paths']['model_dir']=str(root/'models')
    cfg['recommend']['candidate']['threads']=1
    cfg['recommend']['mab']['epsilon']=0.
    at=pd.Timestamp(cfg['simulator']['reference_time']); train_end=at-pd.Timedelta(days=2); valid_end=at-pd.Timedelta(days=1)
    products=pd.DataFrame(dict(product_id=[f'p{i:02}' for i in range(30)],price=np.arange(30)+100.,created_at=[at-pd.Timedelta(days=5)]*30))
    for field in ITEM_FIELDS: products[field]=[f'{field}-{i%5}' for i in range(30)]
    users=pd.DataFrame(dict(user_id=['u'],age_group=['18-24'],gender=['F'],signup_at=[at-pd.Timedelta(days=10)],persona=['hidden']))
    train=pd.DataFrame([dict(event_id=f'e{i}',user_id='u',product_id=f'p{i%2:02}',event_type='view',session_id='s',timestamp=train_end-pd.Timedelta(minutes=10-i),impression_id=None) for i in range(6)])
    valid=train.iloc[:1].copy(); valid['event_id']='valid'; valid['timestamp']=valid_end
    data_root=Path(cfg['paths']['data_dir']); (data_root/'split').mkdir(parents=True)
    frames={'products.parquet':products,'users.parquet':users,'split/train.parquet':train,'split/valid.parquet':valid}
    for name,frame in frames.items(): frame.to_parquet(data_root/name,index=False)
    manifest=dict(generation_fingerprint='ranking-fixture-v1',file_hashes={name:file_hash(data_root/name) for name in frames},
                  boundaries={'train':{'start':train.timestamp.min().isoformat(),'end':train_end.isoformat()},'valid':{'start':valid_end.isoformat(),'end':valid_end.isoformat()}},counts={'products':30,'users':1,'events':7})
    write_json(data_root/'split_manifest.json',manifest)
    data=dict(products=products,users=users,train=train,valid=valid,manifest=manifest)
    encoder=FeatureEncoder.fit(products,users,train_end); table=encoder.item_table(products)
    torch.manual_seed(cfg['seed']); torch.set_num_threads(1)
    candidate=TwoTower(encoder,table,cfg['recommend']['candidate']); path=Path(cfg['paths']['model_dir'])/'v1.0'
    meta=save_bundle(path,candidate,encoder,table,cfg,data,1,.5); build_index(path,candidate,table,cfg,meta)
    ranking=RankingEncoder(encoder,np.zeros(len(DENSE_FIELDS),np.float32),np.ones(len(DENSE_FIELDS),np.float32),True)
    model=DeepFM(ranking.cardinalities,len(DENSE_FIELDS),cfg['recommend']['ranking'])
    # A controlled cross-affinity fixture makes the API adaptation assertion
    # deterministic; actual learned-model quality is measured in full artifacts.
    with torch.no_grad():
        for parameter in model.parameters(): parameter.zero_()
        model.dense_linear.weight[0,4]=4.
        model.dense_linear.weight[0,5]=2.
    ranking_path=path/'ranking'; ranking_path.mkdir(); torch.save(model.state_dict(),ranking_path/'deepfm.pt'); write_json(ranking_path/'features.json',ranking.to_dict())
    write_json(ranking_path/'meta.json',dict(data_fingerprint=manifest['generation_fingerprint'],catalog_sha256=manifest['file_hashes']['products.parquet'],
                config_fingerprint=fingerprint(cfg['recommend']['ranking']),feature_fingerprint=ranking.digest,
                hashes={name:file_hash(ranking_path/name) for name in ['deepfm.pt','features.json']}))
    with torch.inference_mode(): vectors=candidate.encode_items(torch.arange(len(table.ids))).numpy()
    session=SessionEncoder(vectors,cfg['recommend']['session']); session_path=path/'session'; session_path.mkdir()
    torch.save(session.state_dict(),session_path/'session.pt'); write_json(session_path/'item_ids.json',table.ids)
    write_json(session_path/'meta.json',dict(config_fingerprint=fingerprint(cfg['recommend']['session']),data_fingerprint=manifest['generation_fingerprint'],
               candidate_sha256=meta['hashes']['two_tower.pt'],hashes={name:file_hash(session_path/name) for name in ['session.pt','item_ids.json']}))
    return cfg,data
