"""B factory uses the shared create_service(cfg, store) contract without editing C."""
from __future__ import annotations

from typing import Any

import copy
import json
import os
from pathlib import Path

from src.recommendation.datasets import read_data
from src.recommendation.index import load_index
from src.recommendation.runtime import configure_inference
from src.recommendation.train_two_tower import load_bundle
from src.recommendation.train_deepfm import load_ranking,bundle_path
from src.recommendation.train_session import load_session,session_path
from src.recommendation.recommender import Recommender


def create_service(cfg: dict, store: Any, *, data: dict | None = None) -> Recommender | None:
    """Reuse read_data's validated dataset when the caller already loaded it."""
    cfg=copy.deepcopy(cfg)
    if os.getenv('RECOMMEND_MODEL_DIR'): cfg['paths']['model_dir']=os.environ['RECOMMEND_MODEL_DIR']
    candidate_path=Path(cfg['recommend'].get('candidate_bundle',Path(cfg['paths']['model_dir'])/'v1.0'))
    if not candidate_path.exists(): return None
    # A B3a bundle explicitly declares its ANN as planned, so no serving model
    # exists yet. A B3b bundle declaring an existing index still fails if damaged.
    candidate_meta_path=candidate_path/'meta.json'
    if candidate_meta_path.exists() and not (candidate_path/'index_manifest.json').exists():
        declared=json.loads(candidate_meta_path.read_text())
        if 'planned_B3b' in declared.get('contract',{}) and 'index_manifest.json' not in declared.get('hashes',{}):
            return None
    ranking_path=bundle_path(cfg)
    if not ranking_path.exists(): return None
    configure_inference(cfg['recommend']['candidate'],with_faiss=True)
    try:
        if data is None:
            data=read_data(cfg['paths']['data_dir'],'valid')
        if hasattr(store, 'configure_categories'):
            field = cfg['recommend']['reranking']['category_field']
            store.configure_categories(data['products'].set_index('product_id')[field].astype(str).to_dict())
        candidate,encoder,table,candidate_meta=load_bundle(candidate_path,data,cfg)
        index,_=load_index(candidate_path,table,candidate_meta)
        ranker,ranking_encoder,ranking_meta=load_ranking(cfg,data)
        session=None; session_meta=None
        if cfg['recommend']['session']['enabled']:
            if not session_path(cfg).exists(): return None
            session,session_meta=load_session(cfg,data,table,candidate_meta)
        service = Recommender(cfg,store,data,candidate,encoder,table,index,ranker,ranking_encoder,session)
        service.bundle_metadata = dict(candidate=candidate_meta, ranking=ranking_meta, session=session_meta)
        return service
    except FileNotFoundError as error:
        raise ValueError('present recommendation bundle is incomplete') from error
