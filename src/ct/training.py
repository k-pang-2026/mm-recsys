"""Fresh chronological snapshots, real B trainers and paired validation comparison."""
from __future__ import annotations

from typing import Any

import copy
import json
from pathlib import Path
import shutil
import tempfile

import pandas as pd

from src.common.artifacts import file_hash, fingerprint, write_json
from src.simulator.split import chronological_split


def snapshot(source: Path, target: Path, events: pd.DataFrame, impressions: pd.DataFrame,
             cfg: dict) -> dict:
    """Caller supplies observed events only; original dataset and held-out test stay untouched."""
    original = json.loads((source / 'split_manifest.json').read_text())
    for name in ('products.parquet', 'users.parquet'):
        if file_hash(source / name) != original['file_hashes'][name]:
            raise ValueError(f'source checksum mismatch: {name}')
    if target.exists():
        raise ValueError('snapshot destination already exists')
    for frame, field in ((events, 'event_id'), (impressions, 'impression_id')):
        if frame[field].duplicated().any():
            raise ValueError(f'duplicate {field}')
    if events.empty or events.timestamp.isna().any() or impressions.exposed_at.isna().any():
        raise ValueError('missing observation time')
    ordered = events.sort_values(['timestamp', 'event_id'], kind='stable')
    through = ordered.timestamp.max()
    impressions = impressions[impressions.exposed_at <= through].copy()
    splits = chronological_split(ordered, cfg['split'])
    if any(part.empty for part in splits.values()):
        raise ValueError('not enough distinct times for fresh train/valid/test splits')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent, prefix='.ct-snapshot-') as temporary:
        root = Path(temporary) / 'snapshot'; (root / 'split').mkdir(parents=True)
        for name in ('products.parquet', 'users.parquet'):
            shutil.copy2(source / name, root / name)
        ordered.to_parquet(root / 'events.parquet', index=False)
        impressions.to_parquet(root / 'impressions.parquet', index=False)
        for name, frame in splits.items():
            frame.to_parquet(root / 'split' / f'{name}.parquet', index=False)
        files = ['products.parquet', 'users.parquet', 'events.parquet', 'impressions.parquet',
                 'split/train.parquet', 'split/valid.parquet', 'split/test.parquet']
        hashes = {name: file_hash(root / name) for name in files}
        manifest = dict(generator_version='ct-observed-snapshot-v1', scale=cfg['scale'], seed=cfg['seed'],
                        generation_fingerprint=fingerprint(dict(files=hashes, seed=cfg['seed'], split=cfg['split'])),
                        parent_fingerprint=original['generation_fingerprint'], file_hashes=hashes,
                        counts=dict(products=len(pd.read_parquet(root / 'products.parquet')),
                                    users=len(pd.read_parquet(root / 'users.parquet')),
                                    events=len(ordered), impressions=len(impressions)),
                        split_counts={name: len(frame) for name, frame in splits.items()},
                        boundaries={name: dict(start=frame.timestamp.min().isoformat(),
                                               end=frame.timestamp.max().isoformat()) for name, frame in splits.items()},
                        observed_through=through.isoformat(),
                        scope='new chronological snapshot; train/valid only for fitting/selection; test unopened')
        write_json(root / 'split_manifest.json', manifest)
        root.rename(target)
    return manifest


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


def validation(service: Any, cfg: dict) -> dict:
    from src.recommendation.train_deepfm import prepare, tensors, probabilities, measure
    from src.recommendation.ranking_features import HistoryIndex
    from src.recommendation.datasets import cutoff_for
    from src.evaluation.metrics import hit_rate_at_k
    from src.recommendation.recommender import Recommender
    from src.serving.memory_store import MemoryFeatureStore
    data, labels, _ = prepare(cfg, 'valid')
    manifest = data['manifest']
    if set(data['products'].product_id.astype(str)) != set(service.table.ids[1:]):
        raise ValueError('validation catalog differs; explicit catalog migration required')
    at = cutoff_for(data, 'valid')
    history = HistoryIndex(data['train'], service.table)
    sparse, dense = service.ranking_encoder.transform(labels['valid'], data['users'], service.table,
                                                       history, freeze_at=at)
    values = tensors(labels['valid'], sparse, dense)
    metrics = measure(values, probabilities(service.ranker, values, cfg['recommend']['ranking']['batch_size']))
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
