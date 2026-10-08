"""Train/valid-only data diagnostics: test outcomes are deliberately never opened here."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from src.common.artifacts import write_json
from src.common.config import load_config
from src.evaluation.metrics import recall_at_k


def diagnose(cfg: dict, data_dir: Path | None = None) -> dict:
    root=data_dir or Path(cfg['paths']['data_dir'])
    products=pd.read_parquet(root/'products.parquet')
    train=pd.read_parquet(root/'split/train.parquet');valid=pd.read_parquet(root/'split/valid.parquet')
    manifest=json.loads((root/'split_manifest.json').read_text())
    cutoff=train.timestamp.max()
    catalog=products[products.created_at<=cutoff].reset_index(drop=True)
    ids=catalog.product_id.to_numpy();idset=set(ids)
    popularity=train[train.event_type.isin(['view','cart','purchase'])].product_id.value_counts()
    pop=catalog.product_id.map(popularity).fillna(0).to_numpy(dtype=float)
    pop_top=ids[np.argsort(-pop,kind='stable')[:300]].tolist()
    truth=valid[valid.event_type.isin(['cart','purchase'])].groupby('user_id').product_id.apply(set)
    visible=train[train.product_id.notna()].merge(products[['product_id','category_l3','brand','price']],on='product_id',validate='many_to_one')
    histories={key:frame.tail(cfg['recommend']['candidate']['history_n']) for key,frame in visible.groupby('user_id',sort=False)}
    category=catalog.category_l3.to_numpy();brand=catalog.brand.to_numpy();prices=catalog.price.to_numpy()
    results=[];unavailable=0;cold=0
    for user,targets in truth.items():
        unavailable+=len(targets-idset)
        history=histories.get(user)
        if history is None or len(history)<cfg['recommend']['cold_start_min_events']:cold+=1
        if history is None:
            top=pop_top
        else:
            # Observable history only: no simulator hidden tastes or future targets.
            cats=history.category_l3.value_counts(normalize=True).to_dict()
            brands=history.brand.value_counts(normalize=True).to_dict()
            score=np.array([cats.get(x,0) for x in category])*4
            score+=np.array([brands.get(x,0) for x in brand])*2
            mean_price=max(float(history.price.mean()),1)
            score-=.25*np.abs(np.log(np.maximum(prices,1)/mean_price))
            score+=.1*np.log1p(pop)
            top=ids[np.argsort(-score,kind='stable')[:300]].tolist()
        results.append({'user_id':user,'targets':len(targets),'history_recall':recall_at_k(top,targets,300),
                        'popularity_recall':recall_at_k(pop_top,targets,300)})
    persona=train.merge(pd.read_parquet(root/'users.parquet')[['user_id','persona']],on='user_id')
    rates=persona.groupby('persona').event_type.apply(lambda x:float((x=='purchase').mean())).to_dict()
    result={'status':'PASS','scale':cfg['scale'],'data_fingerprint':manifest['generation_fingerprint'],
            'evaluation_split':'valid','test_outcomes_read':False,'cutoff':str(cutoff),
            'eligible_catalog':len(catalog),'evaluated_users':len(results),'cold_users':cold,
            'unavailable_truth_items':unavailable,'event_distribution':train.event_type.value_counts().to_dict(),
            'persona_purchase_event_rates':rates,
            'valid_history_recall_at_300':float(np.mean([x['history_recall'] for x in results])) if results else None,
            'valid_popularity_recall_at_300':float(np.mean([x['popularity_recall'] for x in results])) if results else None,
            'uniform_catalog_expected_recall':min(1,300/max(len(catalog),1)),
            'note':'Train/valid pilot, not Two Tower acceptance; frozen test metrics remain UNMEASURED'}
    return result


def main() -> None:
    parser=argparse.ArgumentParser();parser.add_argument('--data-dir',type=Path);args=parser.parse_args()
    cfg=load_config();result=diagnose(cfg,args.data_dir)
    suffix='_full' if cfg['scale']=='full' else ''
    write_json(Path(cfg['paths']['results_dir'])/f'data_diagnostics{suffix}.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
