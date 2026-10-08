"""Validate generated schema/causality, without evaluating models on test outcomes."""
from __future__ import annotations

import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pandas as pd
from src.common.config import load_config
from src.simulator.generate import generate


def main() -> None:
    cfg=load_config();manifest=generate(cfg);root=Path(cfg['paths']['data_dir'])
    products=pd.read_parquet(root/'products.parquet');users=pd.read_parquet(root/'users.parquet')
    events=pd.read_parquet(root/'events.parquet');exposures=pd.read_parquet(root/'impressions.parquet')
    for frame,key,count in [(products,'product_id','n_products'),(users,'user_id','n_users'),(events,'event_id','n_events')]:
        assert len(frame)==cfg['simulator'][count] and frame[key].is_unique and frame[key].notna().all(),key
    assert set(events.user_id)<=set(users.user_id)
    assert events.timestamp.is_monotonic_increasing and events.timestamp.notna().all()
    assert set(events.event_type)==set(cfg['simulator']['event_types'])
    assert events.loc[events.event_type!='search','product_id'].notna().all()
    assert set(events.product_id.dropna())<=set(products.product_id)
    created=products.set_index('product_id').created_at
    referenced=events[events.product_id.notna()]
    assert (referenced.timestamp>=referenced.product_id.map(created)).all()
    assert exposures.impression_id.is_unique and not exposures.duplicated(['request_id','product_id']).any()
    assert (exposures.exposed_at>=exposures.product_id.map(created)).all()
    assert exposures.groupby('request_id').size().eq(cfg['simulator']['impressions_per_view']).all()
    assert set(events.loc[events.event_type=='view','impression_id'])<=set(exposures.impression_id)
    split=[pd.read_parquet(root/f'split/{name}.parquet',columns=['event_id','timestamp']) for name in ['train','valid','test']]
    assert sum(len(frame) for frame in split)==len(events)
    assert pd.concat(split).event_id.is_unique
    assert split[0].timestamp.max()<split[1].timestamp.min()<=split[1].timestamp.max()<split[2].timestamp.min()
    assert abs(len(split[0])/len(events)-cfg['split']['train'])<.02
    assert abs(len(split[1])/len(events)-cfg['split']['valid'])<.02
    counts=users.persona.value_counts(normalize=True)
    assert all(abs(counts.get(name,0)-spec['ratio'])<=.02 for name,spec in cfg['simulator']['personas'].items())
    print(json.dumps({'status':'PASS','scale':cfg['scale'],'counts':manifest['counts'],
                      'split_counts':manifest['split_counts'],'data_fingerprint':manifest['generation_fingerprint'],
                      'model_test_metrics':'UNMEASURED'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
