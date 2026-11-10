"""Fresh chronological snapshots, real B trainers and paired validation comparison."""
from __future__ import annotations

from typing import Any

import copy
import json
from pathlib import Path

import pandas as pd

from src.common.artifacts import file_hash, fingerprint, write_json
from src.ct.snapshot import snapshot as snapshot


def train_all(cfg: dict, work: Path) -> tuple[dict, Path]:
    from src.recommendation.train_two_tower import train as candidate
    from src.recommendation.train_deepfm import train as ranking
    from src.recommendation.train_session import train as session
    from src.common.seed import set_seed
    if cfg['seed'] != 42:
        raise ValueError('CT seed must remain 42')
    set_seed(cfg['seed'])
    local = copy.deepcopy(cfg)
    local['paths']['model_dir'] = str(work / 'models')
    local['paths']['results_dir'] = str(work / 'results')
    local['recommend'].pop('candidate_bundle', None)
    if Path(local['paths']['model_dir']).exists():
        raise ValueError('training output already exists')
    reports = dict(candidate=candidate(local), ranking=ranking(local), session=session(local))
    return reports, Path(local['paths']['model_dir']) / 'v1.0'


def validation_data(cfg: dict) -> tuple[dict, pd.DataFrame]:
    from src.recommendation.datasets import read_data
    from src.recommendation.ranking_labels import read_impressions, build_labels
    data = read_data(cfg['paths']['data_dir'], 'valid')
    impressions = read_impressions(cfg['paths']['data_dir'], data['manifest'])
    events = pd.concat([data['train'], data['valid']], ignore_index=True)
    boundary = data['manifest']['boundaries']['valid']
    # CT evaluates valid only; constructing unused train labels inflates peak memory.
    labels, _ = build_labels(impressions, events[events.timestamp <= pd.Timestamp(boundary['end'])],
                            pd.Timestamp(boundary['start']), pd.Timestamp(boundary['end']),
                            cfg['recommend']['ranking']['attribution_seconds'])
    return data, labels


def validation(service: Any, cfg: dict) -> dict:
    from src.recommendation.train_deepfm import tensors, probabilities, measure
    from src.recommendation.ranking_features import HistoryIndex
    from src.recommendation.datasets import cutoff_for
    from src.evaluation.metrics import hit_rate_at_k
    from src.recommendation.recommender import Recommender
    from src.serving.memory_store import MemoryFeatureStore
    data, labels = validation_data(cfg)
    manifest = data['manifest']
    if set(data['products'].product_id.astype(str)) != set(service.table.ids[1:]):
        raise ValueError('validation catalog differs; explicit catalog migration required')
    at = cutoff_for(data, 'valid')
    history = HistoryIndex(data['train'], service.table)
    sparse, dense = service.ranking_encoder.transform(labels, data['users'], service.table,
                                                       history, freeze_at=at)
    values = tensors(labels, sparse, dense)
    metrics = measure(values, probabilities(service.ranker, values, cfg['recommend']['ranking']['batch_size']))
    del labels, sparse, dense, values, history
    evaluation_cfg = copy.deepcopy(service.cfg)
    evaluation_cfg['recommend']['record_exposures'] = False
    evaluation_cfg['recommend']['mab']['epsilon'] = 0.
    evaluator = Recommender(evaluation_cfg, MemoryFeatureStore(), data, service.candidate_model,
                           service.encoder, service.table, service.candidate.index, service.ranker,
                           service.ranking_encoder, service.session_model, at=at, history=data['train'])
    future = data['valid']
    target = future[future.event_type.isin(cfg['recommend']['evaluation']['target_events']) & future.product_id.notna()]
    truth = {str(uid): set(group.product_id.astype(str)) for uid, group in target.groupby('user_id')}
    hits = [hit_rate_at_k([r.product_id for r in evaluator.recommend(uid, 50).recommendations], relevant, 50)
            for uid, relevant in sorted(truth.items())]
    return dict(ctr_auc=metrics['ctr']['auc'], ctr_logloss=metrics['ctr']['logloss'],
                hit_rate_at_50=sum(hits) / len(hits) if hits else None,
                truth_users=len(hits), ctr_samples=metrics['ctr']['samples'],
                validation_fingerprint=fingerprint(dict(manifest=manifest, split='valid',
                    contract='fixed-origin unique future cart/purchase top50; mature linked CTR; epsilon=0')))
