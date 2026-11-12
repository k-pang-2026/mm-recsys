from __future__ import annotations

import copy
from pathlib import Path
import pandas as pd
import pytest
from PIL import Image
from src.common.config import load_config
from src.recommendation.datasets import context_for
from src.recommendation.features import FeatureEncoder
from src.simulator.generate import generate
from src.simulator.split import chronological_split
from src.evaluation.diagnose_data import diagnose


@pytest.fixture
def tiny_config():
    cfg=copy.deepcopy(load_config())
    cfg['simulator'].update(n_products=450,n_users=120,n_events=4000)
    return cfg


def test_generation_causality_and_reproducibility(tmp_path,tiny_config):
    first=generate(tiny_config,tmp_path/'first');second=generate(tiny_config,tmp_path/'second')
    assert first['file_hashes']==second['file_hashes']
    assert generate(tiny_config,tmp_path/'first')==first
    data=tmp_path/'first';products=pd.read_parquet(data/'products.parquet')
    users=pd.read_parquet(data/'users.parquet');events=pd.read_parquet(data/'events.parquet')
    exposures=pd.read_parquet(data/'impressions.parquet')
    assert products.product_id.is_unique and users.user_id.is_unique and events.event_id.is_unique
    assert set(events.event_type)=={'search','view','cart','purchase'}
    assert events.timestamp.is_monotonic_increasing
    joined=events[events.product_id.notna()].merge(products[['product_id','created_at']],on='product_id')
    assert (joined.timestamp>=joined.created_at).all()
    observed=events[events.event_type=='view']
    assert set(observed.impression_id)<=set(exposures.impression_id)
    assert not exposures.duplicated(['request_id','product_id']).any()
    assert (exposures.merge(products[['product_id','created_at']],on='product_id').exposed_at>=
            exposures.merge(products[['product_id','created_at']],on='product_id').created_at).all()
    with Image.open(data/products.image_path.iloc[0]) as image:assert image.size==(224,224)
    assert set(products.visual_group)==set(products.image_sha256)
    assert (data/'image_manifest.json').is_file()
    train=pd.read_parquet(data/'split/train.parquet');valid=pd.read_parquet(data/'split/valid.parquet');test=pd.read_parquet(data/'split/test.parquet')
    assert train.timestamp.max()<valid.timestamp.min()<test.timestamp.min()
    assert len(train)+len(valid)+len(test)==4000
    uid=train.user_id.iloc[0];cutoff=valid.timestamp.min()
    encoder=FeatureEncoder.fit(products,users,cutoff);table=encoder.item_table(products)
    user=users.set_index('user_id').loc[uid].to_dict()
    history=events[events.user_id==uid]
    before=context_for(history[history.timestamp<cutoff],user,encoder,table,cutoff,50)
    after=context_for(history,user,encoder,table,cutoff,50)
    assert (before.history==after.history).all() and before.purchased==after.purchased
    # Removing test outcomes cannot affect the pilot, proving it is valid-only.
    (data/'split/test.parquet').unlink()
    result=diagnose(tiny_config,data)
    assert result['test_outcomes_read'] is False and result['evaluated_users']>0


def test_stale_dataset_is_not_silently_reused(tmp_path,tiny_config):
    generate(tiny_config,tmp_path)
    tiny_config['seed']=43
    with pytest.raises(ValueError,match='fingerprint'):generate(tiny_config,tmp_path)


def test_timestamp_ties_remain_in_one_split():
    frame=pd.DataFrame({'event_id':[str(x) for x in range(10)],'timestamp':[1]*8+[2,3]})
    split=chronological_split(frame,{'train':.5,'valid':.3,'test':.2})
    for a,b in [('train','valid'),('valid','test')]:
        if len(split[a]) and len(split[b]):assert split[a].timestamp.max()<split[b].timestamp.min()


def test_generation_publishes_within_mounted_filesystem(tmp_path,tiny_config,monkeypatch):
    import errno
    root=tmp_path/'mounted-data'
    original=Path.rename
    def rename(source,target):
        if source.is_relative_to(root)!=Path(target).is_relative_to(root):
            raise OSError(errno.EXDEV,'cross-device rename')
        return original(source,target)
    monkeypatch.setattr(Path,'rename',rename)
    result=generate(tiny_config,root)
    assert result['counts']['products']==450
    assert (root/'split_manifest.json').is_file()
    assert len(list((root/'images').glob('*.jpg')))==450
    assert not list(root.glob('.generation-*'))
