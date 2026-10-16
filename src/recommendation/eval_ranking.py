"""Frozen-origin end-to-end ranking comparison and separate CTR/CVR metrics."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from collections import Counter

import numpy as np
import pandas as pd

from src.common.artifacts import file_hash,fingerprint,write_json
from src.common.config import load_config
from src.evaluation.metrics import hit_rate_at_k,ndcg_at_k,coverage
from src.recommendation.datasets import cutoff_for
from src.recommendation.train_deepfm import prepare,load_ranking,tensors,probabilities,measure
from src.recommendation.train_two_tower import load_bundle
from src.recommendation.ranking_features import HistoryIndex
from src.recommendation.index import load_index
from src.recommendation.runtime import configure_inference
from src.recommendation.recommender import Recommender
from src.recommendation.feature_store import RecommendationFeatureStore
from src.recommendation.train_session import load_session


def evaluate(cfg: dict,split: str,with_session: bool=False,reuse: Path | None=None,output: Path | None=None) -> dict:
    started=time.perf_counter(); configure_inference(cfg['recommend']['candidate'],with_faiss=True)
    anchor=None
    if reuse is not None:
        if not with_session: raise ValueError('reuse is for B5 constraint re-evaluation only')
        from src.recommendation.datasets import read_data
        data=read_data(cfg['paths']['data_dir'],split)
        anchor=json.loads(reuse.read_text()); labels=None; diagnostics={split:anchor['labels']}
    else:
        data,labels,diagnostics=prepare(cfg,split)
    candidate_path=Path(cfg['recommend'].get('candidate_bundle',Path(cfg['paths']['model_dir'])/'v1.0'))
    candidate,encoder,table,candidate_meta=load_bundle(candidate_path,data,cfg)
    index,_=load_index(candidate_path,table,candidate_meta)
    model,ranking_encoder,ranking_meta=load_ranking(cfg,data)
    if anchor and (anchor['split']!=split or anchor['data_fingerprint']!=data['manifest']['generation_fingerprint']
                   or anchor['ranking_model_sha256']!=ranking_meta['hashes']['deepfm.pt']
                   or anchor['candidate_model_sha256']!=candidate_meta['hashes']['two_tower.pt']):
        raise ValueError('reused classification/baseline differs from frozen model/data')
    if split=='test':
        selection=json.loads((Path(cfg['paths']['results_dir'])/f'ranking_selection_{cfg["scale"]}.json').read_text())
        if selection['model_sha256']!=ranking_meta['hashes']['deepfm.pt'] or selection['config_fingerprint']!=ranking_meta['config_fingerprint']:
            raise ValueError('test model differs from frozen valid selection')
    at=cutoff_for(data,split); history=data['train'] if split=='valid' else pd.concat([data['train'],data['valid']],ignore_index=True)
    if anchor:
        classification=anchor['classification']
    else:
        assert labels is not None
        history_index=HistoryIndex(history,table,popularity_events=data['train'])
        sparse,dense=ranking_encoder.transform(labels[split],data['users'],table,history_index,freeze_at=at)
        values=tensors(labels[split],sparse,dense); classification=measure(values,probabilities(model,values,cfg['recommend']['ranking']['batch_size']))
        del values, sparse, dense, labels, history_index
    session=None
    if with_session: session,_=load_session(cfg,data,table,candidate_meta)
    store=RecommendationFeatureStore(cfg,data['products'])
    recommender=Recommender(cfg,store,data,candidate,encoder,table,index,model,ranking_encoder,session,at=at,history=history)
    future=data[split]; target=future[future.event_type.isin(cfg['recommend']['evaluation']['target_events']) & future.product_id.notna()]
    truth={str(uid):set(g.product_id.astype(str)) for uid,g in target.groupby('user_id')}
    user_ids=sorted(data['users'].user_id.astype(str))[:cfg['recommend']['evaluation']['coverage_users']]
    baseline=[]; ranked=[]; final=[]; evaluated_truth=[]; covered: dict = {}; cold=0; violations=0
    infeasible_pools=0; feasible_violations=0; violation_types: Counter = Counter(); violation_examples: list[dict] = []
    modes=['two_tower','deepfm']+(['b5'] if with_session else [])
    for name in modes: covered[name]=set()
    for i,uid in enumerate(user_ids):
        context=recommender.context(uid,[]); cold+=int(context.history_count<cfg['recommend']['cold_start_min_events'])
        baseline_top=[]; rank_top=[]
        if not anchor:
            candidates=recommender.candidate.retrieve(context,cfg['recommend']['candidate_k'],cfg['recommend']['exclude_purchased'])
            baseline_top=candidates[:50]
            recommender.cfg['recommend']['enable_reranking']=False
            recommender.cfg['recommend']['record_exposures']=False
            rank_top=[x.product_id for x in recommender.recommend(uid,50).recommendations]
            covered['two_tower'].update(baseline_top); covered['deepfm'].update(rank_top)
        final_top=[]
        if with_session:
            recommender.cfg['recommend']['enable_reranking']=True
            recommender.cfg['recommend']['record_exposures']=True
            final_top=[x.product_id for x in recommender.recommend(uid,50).recommendations]
            covered['b5'].update(final_top); violations+=int(bool(recommender.last_diagnostics.get('violations')))
            details=recommender.last_diagnostics
            infeasible_pools+=int(not details['diversity_feasible_for_returned'])
            feasible_violations+=int(bool(details['violations']) and details['diversity_feasible_for_returned'])
            violation_types.update(details['violations'])
            if details['violations'] and len(violation_examples)<5: violation_examples.append(dict(user_id=uid,**details))
        if uid in truth:
            evaluated_truth.append(truth[uid]); baseline.append(baseline_top); ranked.append(rank_top)
            if with_session: final.append(final_top)
        if (i+1)%1000==0: print(f'{split} evaluated_users={i+1}',flush=True)
    metrics={name:anchor['metrics'][name] for name in ['two_tower','deepfm']} if anchor else {}
    for name,rows in ([] if anchor else [('two_tower',baseline),('deepfm',ranked)])+([('b5',final)] if with_session else []):
        metrics[name]=dict(hit_rate_at_50=float(np.mean([hit_rate_at_k(r,t,50) for r,t in zip(rows,evaluated_truth)])),
                           ndcg_at_50=float(np.mean([ndcg_at_k(r,t,50) for r,t in zip(rows,evaluated_truth)])),
                           coverage=coverage(covered[name],len(data['products'])),unique_recommended_items=len(covered[name]))
    lift={key:metrics['deepfm'][key]-metrics['two_tower'][key] for key in ['hit_rate_at_50','ndcg_at_50','coverage']}
    report=dict(status='PASS',acceptance='UNMEASURED',scale=cfg['scale'],split=split,classification=classification,
                labels=diagnostics[split],metrics=metrics,deepfm_absolute_lift=lift,truth_users=len(evaluated_truth),coverage_users=len(user_ids),cold_users=cold,
                catalog_items=len(data['products']),data_counts=data['manifest']['counts'],cutoff=at.isoformat(),
                contract='fixed origin; nonempty unique cart/purchase truth; unavailable truth retained; coverage denominator full catalog',
                session_evaluation='no within-evaluation session clicks in fixed-origin metrics; live adaptation tested separately',
                b5_constraint_violations=violations,data_fingerprint=data['manifest']['generation_fingerprint'],
                b5_infeasible_candidate_pools=infeasible_pools,b5_feasible_pool_violations=feasible_violations,
                b5_violation_types=dict(violation_types),b5_violation_examples=violation_examples,
                scoring=recommender.scoring,config_fingerprint=fingerprint(cfg['recommend']),ranking_model_sha256=ranking_meta['hashes']['deepfm.pt'],
                candidate_model_sha256=candidate_meta['hashes']['two_tower.pt'],elapsed_seconds=time.perf_counter()-started)
    if anchor:
        assert reuse is not None
        report['reused_unchanged_measurements']=dict(source=str(reuse),sha256=file_hash(reuse),
            scope='CTR/CVR classification and Two Tower/DeepFM baseline metrics from same frozen model/data; only B5 constraints re-executed')
        if report['truth_users']!=anchor['truth_users'] or report['coverage_users']!=anchor['coverage_users'] or report['cutoff']!=anchor['cutoff']:
            raise ValueError('re-evaluation cohort/cutoff changed')
    report['checks']={'ctr_auc':classification['ctr']['auc'] is not None and classification['ctr']['auc']>=cfg['targets']['auc'],
                      'hit_rate_at_50':metrics['b5' if with_session else 'deepfm']['hit_rate_at_50']>=cfg['targets']['hit_rate_at_50'],
                      'ndcg_at_50':metrics['b5' if with_session else 'deepfm']['ndcg_at_50']>=cfg['targets']['ndcg_at_50'],
                      'coverage':metrics['b5' if with_session else 'deepfm']['coverage']>=cfg['targets']['coverage']}
    if cfg['scale']=='full' and split=='test':
        report['measured_quality_status']='PASS' if all(report['checks'].values()) else 'FAIL'
    output=output or Path(cfg['paths']['results_dir'])/f'ranking_{cfg["scale"]}_{split}{"_b5" if with_session else ""}.json'
    write_json(output,report); print(f'result={output}; metrics={metrics}',flush=True); return report


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument('--split',choices=['valid','test'],required=True); parser.add_argument('--session',action='store_true')
    parser.add_argument('--candidate-bundle',type=Path)
    parser.add_argument('--policy',choices=['ctr_cvr','ctr','rank_fusion'])
    parser.add_argument('--alpha',type=float,default=.5)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--require-quality',action='store_true')
    parser.add_argument('--reuse',type=Path,help='reuse immutable classification/baselines; re-run B5 constraints only')
    args=parser.parse_args(); cfg=load_config()
    if args.candidate_bundle: cfg['recommend']['candidate_bundle']=str(args.candidate_bundle)
    if args.policy: cfg['recommend']['scoring']=dict(strategy=args.policy,**({'alpha':args.alpha} if args.policy=='rank_fusion' else {}))
    if args.reuse and args.policy: parser.error('legacy reuse is incompatible with changed scoring')
    report=evaluate(cfg,args.split,args.session,args.reuse,args.output)
    return 1 if args.require_quality and not all(report['checks'].values()) else 0


if __name__=='__main__': raise SystemExit(main())
