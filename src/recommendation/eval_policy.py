"""Compare inference policies on valid; freeze one eligible policy before test."""
from __future__ import annotations

import argparse
import copy
import json
import os
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from src.common.artifacts import file_hash, fingerprint, write_json
from src.common.config import load_config
from src.evaluation.metrics import hit_rate_at_k, ndcg_at_k, coverage
from src.recommendation.datasets import read_data, cutoff_for
from src.recommendation.feature_store import RecommendationFeatureStore
from src.recommendation.index import load_index
from src.recommendation.recommender import Recommender
from src.recommendation.reranking import Reranker
from src.recommendation.runtime import configure_inference
from src.recommendation.scoring import policy
from src.recommendation.train_deepfm import load_ranking
from src.recommendation.train_session import load_session
from src.recommendation.train_two_tower import load_bundle

POLICIES = [('ctr_cvr', {'strategy':'ctr_cvr'}), ('ctr', {'strategy':'ctr'})] + [
    (f'rank_fusion_{alpha:.2f}', {'strategy':'rank_fusion','alpha':alpha}) for alpha in [.25,.5,.75]]
SOURCES = ['src/recommendation/scoring.py','src/recommendation/recommender.py',
           'src/recommendation/reranking.py','src/recommendation/mab.py',
           'src/recommendation/eval_policy.py']


def isolated_policy(base, spec):
    """Share immutable models/features, never mutable exposure/config/RNG state."""
    service = copy.copy(base)
    service.cfg = copy.deepcopy(base.cfg)
    service.cfg['recommend']['scoring'] = policy(spec)
    service.scoring = policy(spec)
    # Fixed-origin evaluation has no feedback or repeated user visits. Advancing
    # an explicit virtual exposure clock expires request records; arm counts persist.
    service.exposure_clock = [0.]
    service.store = RecommendationFeatureStore(service.cfg, service.data['products'],clock=lambda:service.exposure_clock[0])
    service.rng = np.random.default_rng(service.cfg['seed'] + 20)
    service.reranker = Reranker(service.cfg,service.data['products'])
    service.last_diagnostics = {}
    return service


def quality_checks(metrics, cfg, violations=0):
    return {key:metrics[key] >= cfg['targets'][key] for key in
            ['hit_rate_at_50','ndcg_at_50','coverage']} | {'feasible_pool_constraints':violations == 0}


def choose(rows):
    eligible = [(index,row) for index,row in enumerate(rows)
                if row['operational'] and all(row['checks'].values())]
    if not eligible: return None
    return max(eligible,key=lambda pair:(pair[1]['metrics']['ndcg_at_50'],
        pair[1]['metrics']['hit_rate_at_50'],pair[1]['metrics']['coverage'],-pair[0]))[1]


def evaluate(cfg, split, output: Path, selection_path: Path):
    started = time.perf_counter()
    if os.getenv('PYTHONHASHSEED') != '42': raise ValueError('launch with PYTHONHASHSEED=42')
    configure_inference(cfg['recommend']['candidate'],with_faiss=True)
    frozen = json.loads(selection_path.read_text()) if split == 'test' else None
    if frozen:
        if frozen['status'] != 'SELECTED': raise ValueError('no eligible frozen valid policy; test prohibited')
        for name,digest in frozen['source_hashes'].items():
            if file_hash(Path(name)) != digest: raise ValueError(f'frozen policy source changed: {name}')
    elif selection_path.exists():
        raise ValueError('selection already exists; preserve prior decision in a separate output version')
    data = read_data(cfg['paths']['data_dir'],split)
    candidate_path = Path(cfg['recommend'].get('candidate_bundle',Path(cfg['paths']['model_dir'])/'v1.0'))
    candidate,encoder,table,candidate_meta = load_bundle(candidate_path,data,cfg)
    index,index_meta = load_index(candidate_path,table,candidate_meta)
    model,ranking_encoder,ranking_meta = load_ranking(cfg,data)
    session,session_meta = load_session(cfg,data,table,candidate_meta)
    identity = dict(data_fingerprint=data['manifest']['generation_fingerprint'],
        data_hashes=data['manifest']['file_hashes'],
        candidate_model_sha256=candidate_meta['hashes']['two_tower.pt'],
        candidate_artifact_hashes=candidate_meta['hashes'],
        ranking_model_sha256=ranking_meta['hashes']['deepfm.pt'],
        ranking_artifact_hashes=ranking_meta['hashes'],
        session_model_sha256=session_meta['hashes']['session.pt'],
        session_artifact_hashes=session_meta['hashes'],
        inference_fingerprint=fingerprint({k:v for k,v in cfg['recommend'].items() if k not in ('scoring','enable_reranking','record_exposures')}),
        seed=cfg['seed'], rng_seed=cfg['seed']+20, python_hash_seed='42', scale=cfg['scale'])
    if frozen and {k:cfg['targets'][k] for k in frozen['thresholds']} != frozen['thresholds']: raise ValueError('quality thresholds differ from frozen selection')
    if frozen and identity != frozen['identity']: raise ValueError('test model/data/inference configuration differs from frozen valid policy')
    at = cutoff_for(data,split)
    history = data['train'] if split == 'valid' else pd.concat([data['train'],data['valid']],ignore_index=True)
    base = Recommender(copy.deepcopy(cfg),RecommendationFeatureStore(cfg,data['products']),data,candidate,encoder,table,index,model,ranking_encoder,session,at=at,history=history)
    specs = [(frozen['selected']['name'],frozen['selected']['policy'])] if frozen else POLICIES
    services = {name:isolated_policy(base,spec) for name,spec in specs}
    target = data[split]
    target = target[target.event_type.isin(cfg['recommend']['evaluation']['target_events']) & target.product_id.notna()]
    truth = {str(uid):set(g.product_id.astype(str)) for uid,g in target.groupby('user_id')}
    users = sorted(data['users'].user_id.astype(str))[:cfg['recommend']['evaluation']['coverage_users']]
    names = list(services) + ([] if frozen else ['two_tower'])
    aggregates = {name:dict(hit=0.,ndcg=0.,covered=set(),cold_hit=0.,warm_hit=0.,cold_truth=0,warm_truth=0,
        violations=0,infeasible=0,feasible_violations=0,category=Counter(),rank_shift=0.,examples=[]) for name in names}
    truth_users = cold_users = 0
    candidate_digest = __import__('hashlib').sha256()
    with torch.inference_mode():
        for i,uid in enumerate(users):
            features = base.store.get_features(uid)
            context = base.context(uid,features.recent_clicks)
            cold = context.history_count < cfg['recommend']['cold_start_min_events']; cold_users += int(cold)
            products = base.candidate_products(context,features)
            predictions = base.predict_products(uid,products,features)
            candidate_digest.update(json.dumps([uid,products],separators=(',',':')).encode())
            candidate_digest.update(predictions.tobytes())
            rows = {}
            candidate_ranks = {pid:rank for rank,pid in enumerate(products)}
            for name,service in services.items():
                items = service.rank_products(products,predictions)
                ordered = sorted(items,key=lambda x:(-x.score,x.product_id))
                aggregates[name]['rank_shift'] += float(np.mean([abs(rank-candidate_ranks[x.product_id]) for rank,x in enumerate(ordered)])) if ordered else 0.
                final,diag = service.rerank_items(items,50,context)
                ids = [x.product_id for x in final]; rows[name]=ids
                service.exposure_clock[0] += cfg['recommend']['mab']['exposure_ttl_seconds']
                service.store.record_exposures(uid,ids)
                agg=aggregates[name]; agg['violations'] += int(bool(diag['violations']))
                infeasible = not diag['diversity_feasible_for_returned']; agg['infeasible'] += int(infeasible)
                agg['feasible_violations'] += int(bool(diag['violations']) and not infeasible)
                if diag['violations'] and len(agg['examples'])<5: agg['examples'].append(dict(user_id=uid,returned_ids=ids,**diag))
            if not frozen:
                rows['two_tower'] = base.candidate.retrieve(context,cfg['recommend']['candidate_k'],cfg['recommend']['exclude_purchased'])[:50]
            for name,ids in rows.items():
                agg=aggregates[name]; agg['covered'].update(ids)
                agg['category'].update(base.reranker.categories[pid] for pid in ids)
                if uid in truth:
                    hit=hit_rate_at_k(ids,truth[uid],50); agg['hit']+=hit
                    agg['ndcg']+=ndcg_at_k(ids,truth[uid],50)
                    cohort='cold' if cold else 'warm'; agg[cohort+'_hit']+=hit; agg[cohort+'_truth']+=1
            truth_users += int(uid in truth)
            if (i+1)%1000==0: print(f'{split} evaluated_users={i+1}',flush=True)
    rows=[]
    for name in names:
        agg=aggregates[name]
        metrics=dict(hit_rate_at_50=agg['hit']/truth_users if truth_users else 0.,ndcg_at_50=agg['ndcg']/truth_users if truth_users else 0.,
                     coverage=coverage(agg['covered'],len(data['products'])),unique_recommended_items=len(agg['covered']))
        rows.append(dict(name=name,operational=name!='two_tower',policy=services[name].scoring if name in services else None,
            metrics=metrics,checks=quality_checks(metrics,cfg,agg['feasible_violations']),
            diagnostics=dict(infeasible_candidate_pools=agg['infeasible'],constraint_violations=agg['violations'],feasible_pool_violations=agg['feasible_violations'],
                violation_examples=agg['examples'],mean_absolute_rank_shift=agg['rank_shift']/len(users),
                category_counts=dict(agg['category']),largest_category_share=max(agg['category'].values(),default=0)/max(sum(agg['category'].values()),1),
                cohorts={cohort:dict(truth_users=agg[cohort+'_truth'],hit_rate_at_50=agg[cohort+'_hit']/max(agg[cohort+'_truth'],1)) for cohort in ['cold','warm']},
                exposure_count=sum(s['exposures'] for s in services[name].store.arm_statistics().values()) if name in services else 0)))
    legacy = Path(cfg['paths']['results_dir'])/f'ranking_{cfg["scale"]}_{split}.json'
    if split=='test': legacy=Path(cfg['paths']['results_dir'])/f'ranking_{cfg["scale"]}_{split}_b5.json'
    unchanged=json.loads(legacy.read_text())
    if unchanged['data_fingerprint']!=identity['data_fingerprint'] or unchanged['ranking_model_sha256']!=identity['ranking_model_sha256']:
        raise ValueError('classification reuse differs from frozen data/model')
    report=dict(version='scoring-policy-v2',split=split,identity=identity,cutoff=at.isoformat(),rows=rows,
        coverage_users=len(users),truth_users=truth_users,all_truth_users=len(truth),cold_users=cold_users,catalog_items=len(data['products']),
        contract='fixed origin; nonempty unique cart/purchase truth; unavailable truth retained; full catalog coverage denominator; no offline session clicks',
        candidate_prediction_sha256=candidate_digest.hexdigest(),state_isolation='independent exposure stores and RNG seed42+20 per policy; immutable candidates/predictions shared; virtual exposure TTL clock, cumulative arm counts, no feedback',
        classification=unchanged['classification'],classification_reuse=dict(source=str(legacy),sha256=file_hash(legacy),scope='unchanged frozen classifier/data/labels; no inference policy dependence'),
        test_previously_observed=True,thresholds={k:cfg['targets'][k] for k in ['hit_rate_at_50','ndcg_at_50','coverage']},
        elapsed_seconds=time.perf_counter()-started)
    if split=='valid':
        selected=choose(rows)
        report['selection_status']='SELECTED' if selected else 'WITHHELD'
        write_json(output,report)
        selection=dict(version='scoring-policy-v2',status=report['selection_status'],selected=selected,
            identity=identity,thresholds=report['thresholds'],valid_report=str(output),valid_report_sha256=file_hash(output),
            source_hashes={name:file_hash(Path(name)) for name in SOURCES},
            valid_cohort=dict(coverage_users=len(users),truth_users=truth_users,catalog_items=len(data['products']),cutoff=at.isoformat()),
            selection_rule='eligible operational policies only; NDCG, HitRate, Coverage, earlier experiment',
            test_previously_observed=True,reason='highest eligible valid NDCG' if selected else 'all operational policies missed at least one unchanged target/feasible constraint')
        write_json(selection_path,selection)
    else:
        report['selection_sha256']=file_hash(selection_path)
        report['quality_status']='PASS' if all(rows[0]['checks'].values()) else 'FAIL'
        write_json(output,report)
    print(f'result={output}; metrics='+json.dumps([{k:row[k] for k in ['name','metrics','checks']} for row in rows]),flush=True)
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--split',required=True,choices=['valid','test'])
    parser.add_argument('--output',type=Path)
    parser.add_argument('--selection',type=Path)
    parser.add_argument('--require-quality',action='store_true')
    args=parser.parse_args();cfg=load_config();root=Path(cfg['paths']['results_dir'])
    report=evaluate(cfg,args.split,args.output or root/f'ranking_policy_{cfg["scale"]}_{args.split}.json',args.selection or root/f'ranking_policy_selection_{cfg["scale"]}.json')
    passed=report.get('selection_status')=='SELECTED' if args.split=='valid' else report['quality_status']=='PASS'
    return 1 if args.require_quality and not passed else 0

if __name__=='__main__': raise SystemExit(main())
