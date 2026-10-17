"""Frozen-origin candidate/ranking/final evaluation over one fixed user cohort."""
from __future__ import annotations

import copy
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from src.common.artifacts import fingerprint
from src.common.schemas import UserFeatures
from src.evaluation.metrics import coverage, hit_rate_at_k, ndcg_at_k
from src.evaluation.reporting import relative_lift
from src.recommendation.candidate import top_indices
from src.recommendation.datasets import cutoff_for
from src.recommendation.eval_candidate import Evaluation
from src.recommendation.feature_store import RecommendationFeatureStore
from src.recommendation.index import load_index
from src.recommendation.recommender import Recommender
from src.recommendation.runtime import configure_inference
from src.recommendation.train_deepfm import load_ranking, prepare, tensors, probabilities, measure
from src.recommendation.ranking_features import HistoryIndex
from src.recommendation.train_session import load_session
from src.recommendation.train_two_tower import load_bundle


def aggregate(rows: list[tuple[str, list[str]]], truth: dict[str, set[str]],
              catalog_items: int, k: int = 50) -> dict:
    if catalog_items < 1 or k != 50 or len({uid for uid, _ in rows}) != len(rows):
        raise ValueError('fixed unique user cohort, full catalog denominator and top50 required')
    eligible_rows = [(uid, ids) for uid, ids in rows if truth.get(uid)]
    if any(len(ids) != len(set(ids)) for _, ids in rows):
        raise ValueError('duplicate recommendations')
    covered = {pid for _, ids in rows for pid in ids[:k]}
    return dict(hit_rate_at_50=float(np.mean([hit_rate_at_k(ids, truth[uid], k) for uid, ids in eligible_rows])) if eligible_rows else None,
                ndcg_at_50=float(np.mean([ndcg_at_k(ids, truth[uid], k) for uid, ids in eligible_rows])) if eligible_rows else None,
                coverage=coverage(covered, catalog_items), unique_recommended_items=len(covered),
                truth_users=len(eligible_rows), coverage_users=len(rows), catalog_items=catalog_items)


def evaluate(cfg: dict, split: str) -> dict:
    configure_inference(cfg['recommend']['candidate'], with_faiss=True)
    data, labels, label_diagnostics = prepare(cfg, split)
    root = Path(cfg['paths']['model_dir']) / 'v1.0'
    root = Path(cfg['recommend'].get('candidate_bundle', root))
    candidate, encoder, table, candidate_meta = load_bundle(root, data, cfg)
    index, index_meta = load_index(root, table, candidate_meta)
    ranker, ranking_encoder, ranking_meta = load_ranking(cfg, data)
    session, session_meta = load_session(cfg, data, table, candidate_meta)
    at = cutoff_for(data, split)
    prior = data['train'] if split == 'valid' else pd.concat([data['train'], data['valid']], ignore_index=True)
    history = HistoryIndex(prior, table, popularity_events=data['train'])
    sparse, dense = ranking_encoder.transform(labels[split], data['users'], table, history, freeze_at=at)
    classified = tensors(labels[split], sparse, dense)
    classification = measure(classified, probabilities(ranker, classified, cfg['recommend']['ranking']['batch_size']))
    del labels, classified, sparse, dense, history
    evaluation = Evaluation(data, encoder, table, cfg, split)
    ann = evaluation.ann_metrics(candidate, index)
    candidate_baselines = evaluation.baseline_metrics()
    clock = [0.]
    store = RecommendationFeatureStore(cfg, data['products'], clock=lambda: clock[0])
    service = Recommender(copy.deepcopy(cfg), store, data, candidate, encoder, table, index,
                          ranker, ranking_encoder, session, at=at, history=prior)
    users = sorted(data['users'].user_id.astype(str))[:cfg['recommend']['evaluation']['coverage_users']]
    ranked: dict[str, list[tuple[str, list[str]]]] = {name: [] for name in ('train_popularity', 'two_tower', 'deepfm', 'full_pipeline')}
    popular = table.public_ids(top_indices(evaluation.baselines.popularity[evaluation.eligible], evaluation.eligible, 50))
    cold: Counter[str] = Counter()
    truth = evaluation.truth
    eligible_ids = set(table.public_ids(evaluation.eligible))
    violations = infeasible = all_violations = 0
    with torch.inference_mode():
        for i, uid in enumerate(users):
            context = service.context(uid, [])
            cohort = 'cold' if context.history_count < cfg['recommend']['cold_start_min_events'] else 'warm'
            cold[cohort] += 1
            cold[cohort + '_truth'] += int(uid in truth)
            tower = service.candidate.retrieve(context, cfg['recommend']['candidate_k'], cfg['recommend']['exclude_purchased'])
            products = service.candidate_products(context, UserFeatures())
            predictions = service.predict_products(uid, products, UserFeatures())
            items = service.rank_products(products, predictions)
            deepfm = sorted(items, key=lambda item: (-item.score, item.product_id))[:50]
            final, diagnostics = service.rerank_items(items, 50, context)
            clock[0] += cfg['recommend']['mab']['exposure_ttl_seconds']
            store.record_exposures(uid, [item.product_id for item in final])
            feasible = diagnostics.get('diversity_feasible_for_returned', False)
            all_violations += int(bool(diagnostics.get('violations')))
            violations += int(bool(diagnostics.get('violations')) and feasible)
            infeasible += int(not feasible)
            values = dict(train_popularity=popular, two_tower=tower[:50],
                          deepfm=[item.product_id for item in deepfm], full_pipeline=[item.product_id for item in final])
            for name, ids in values.items():
                if any(pid not in eligible_ids for pid in ids):
                    raise ValueError('future inventory entered evaluation')
                ranked[name].append((uid, ids))
            if (i + 1) % 500 == 0:
                print(f'B8 recommendation {split}: {i + 1}/{len(users)} users', flush=True)
    metrics = {name: aggregate(rows, truth, len(data['products'])) for name, rows in ranked.items()}
    lift = {name: {key: relative_lift(metrics['full_pipeline'][key], row[key])
                   for key in ('hit_rate_at_50', 'ndcg_at_50', 'coverage')}
            for name, row in metrics.items() if name != 'full_pipeline'}
    return dict(status='MEASURED', split=split, cutoff=at.isoformat(),
                candidate=ann, candidate_baselines=candidate_baselines, classification=classification,
                label_diagnostics=label_diagnostics[split], metrics=metrics, relative_lift=lift,
                cohort=dict(**cold, user_ids_sha256=fingerprint(users), total_users=len(users),
                    truth_users=sum(uid in truth for uid in users), all_truth_users=len(truth),
                    empty_truth_users=sum(uid not in truth for uid in users), eligible_catalog=len(evaluation.eligible),
                    unavailable_truth_items=ann['ann_two_tower']['unavailable_truth_items']),
                feasible_constraint_violations=violations, infeasible_candidate_pools=infeasible,
                constraint_violations=all_violations,
                models=dict(candidate=candidate_meta, index=index_meta, ranking=ranking_meta, session=session_meta),
                data_fingerprint=data['manifest']['generation_fingerprint'],
                contract='fixed origin; unique future cart/purchase truth; unavailable truth retained; fixed all-user coverage cohort; full-catalog denominator; top50',
                session_scope='offline fixed-origin has no within-evaluation session clicks or feedback; live session/Redis behavior measured separately',
                state='isolated B5 memory adapter, fixed-seed RNG, virtual exposure clock; no cross-policy feedback')
