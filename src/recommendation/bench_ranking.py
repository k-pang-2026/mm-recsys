"""Full shared-API injection benchmark and observable session/reward evidence."""
from __future__ import annotations

from typing import cast
from fastapi import FastAPI

import argparse
import json
import platform
import copy
import os
import importlib.metadata
import torch
import time
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from src.common.artifacts import file_hash,write_json,fingerprint
from src.common.config import load_config
from src.common.schemas import RecommendResponse
from src.recommendation.datasets import read_data
from src.recommendation.feature_store import RecommendationFeatureStore
from src.serving.main import create_app


def percentiles(values: list[float]) -> dict[str, float]:
    return {f'p{p}_ms':float(np.percentile(values,p)) for p in [50,95,99]}


def benchmark(cfg: dict,b5: bool=True,output: Path | None=None) -> dict:
    cfg=copy.deepcopy(cfg)
    cfg['recommend']['enable_reranking']=b5; cfg['recommend']['session']['enabled']=b5
    cfg['serving']['plugins']['search']='src.recommendation.no_search_plugin'
    data=read_data(cfg['paths']['data_dir']); store=RecommendationFeatureStore(cfg,data['products'])
    users=sorted(data['train'].user_id.unique()); warmup=cfg['benchmark']['warmup']; count=cfg['benchmark']['requests']
    request_records=[]
    native=[]; http=[]; stages: dict[str, list[float]] = {k:[] for k in ['candidate_ms','ranking_ms','reranking_ms']}; responses: list[dict] = []
    startup_started=time.perf_counter()
    with TestClient(create_app(cfg,feature_store=store)) as client:
        startup_ms=(time.perf_counter()-startup_started)*1000
        if cast(FastAPI, client.app).state.recommend is None: raise ValueError('model unavailable during API benchmark')
        service=cast(FastAPI, client.app).state.recommend
        for i in range(warmup+count):
            uid=str(users[i%len(users)]); start=time.perf_counter()
            result=client.get('/api/recommend',params={'user_id':uid,'top_n':50})
            duration=(time.perf_counter()-start)*1000
            if result.status_code!=200: raise ValueError(f'API returned {result.status_code}: {result.text}')
            parsed=RecommendResponse.model_validate(result.json()); latency=parsed.pipeline_latency.model_dump()
            request_records.append(dict(index=i,warmup=i<warmup,user_id=uid,http_status=result.status_code,http_elapsed_ms=duration,pipeline_latency=latency))
            if i>=warmup:
                native.append(latency['total_ms']); http.append(duration)
                for key in stages: stages[key].append(latency[key])
                if len(responses)<5: responses.append(result.json())
        live={}
        if b5:
            # Hold MAB randomness fixed across before/after to isolate the session change.
            rng_state=json.loads(json.dumps(service.rng.bit_generator.state))
            uid=str(users[0]); before=client.get('/api/recommend',params={'user_id':uid,'top_n':10}).json()
            first=before['recommendations'][0]['product_id']; first_category=service.reranker.categories[first]
            chosen=next(p for p in service.fallback_sorted if service.reranker.categories[p]!=first_category and service.table.id_to_index[p] in service.candidate.allowed)
            for i in range(3):
                event=dict(event_id=f'benchmark-click-{i}',user_id=uid,product_id=chosen,event_type='view',session_id='benchmark-session')
                if not client.post('/api/event',json=event).json()['applied']: raise ValueError('controlled click not applied')
            service.rng.bit_generator.state=rng_state
            after=client.get('/api/recommend',params={'user_id':uid,'top_n':10}).json()
            changed=[x['product_id'] for x in before['recommendations']]!=[x['product_id'] for x in after['recommendations']]
            if not changed: raise ValueError('trained-model recommendations did not change after three controlled clicks')
            product=after['recommendations'][0]['product_id']; old=store.arm_statistics()[store.arm_for(product)]
            click=dict(event_id='benchmark-reward-click',user_id=uid,product_id=product,event_type='view')
            purchase=dict(event_id='benchmark-reward-purchase',user_id=uid,product_id=product,event_type='purchase')
            applied=client.post('/api/feedback',json=click).json()['applied']
            click_state=store.arm_statistics()[store.arm_for(product)]
            applied_purchase=client.post('/api/feedback',json=purchase).json()['applied']
            duplicate=client.post('/api/feedback',json=purchase).json()['applied']
            new=store.arm_statistics()[store.arm_for(product)]
            if not applied or not applied_purchase or duplicate or abs(new['reward']-old['reward']-1.)>1e-8:
                raise ValueError('feedback attribution/max/idempotence failed')
            live=dict(status='PASS',user_id=uid,clicked_product=chosen,before=before,after=after,recommendations_changed=changed,
                      recent_clicks=after['session_context']['recent_clicks'],session_interest=after['session_context']['session_interest'],
                      feedback=dict(product_id=product,before=old,click=click_state,purchase=new,duplicate_applied=duplicate),
                      store='B RecommendationFeatureStore injected into unchanged shared create_app; default C store not connected')
    report=dict(status='PASS' if max(np.percentile(native,95),np.percentile(http,95))<=cfg['targets']['recommend_p95_ms'] else 'FAIL',
                acceptance='UNMEASURED',stage='B5' if b5 else 'B4',scale=cfg['scale'],warmup=warmup,requests=count,
                concurrency=1,top_n=50,startup_model_loading_ms=startup_ms,errors=0,request_records=request_records,
                scoring=service.scoring,policy_fingerprint=fingerprint(service.scoring),
                artifact_hashes={name:file_hash(Path(cfg['paths']['model_dir'])/'v1.0'/name) for name in ['two_tower.pt','item_index.faiss','ranking/deepfm.pt','ranking/features.json','session/session.pt']},
                config_fingerprint=fingerprint(cfg),native=percentiles(native),asgi_http=percentiles(http),stage_percentiles={k:percentiles(v) for k,v in stages.items()},
                native_elapsed_ms=native,asgi_http_elapsed_ms=http,sample_responses=responses,live_flow=live,
                measurement_scope='shared FastAPI paths with injected B memory adapter; ASGI TestClient HTTP transport, no TCP/Redis/container',
                environment=dict(platform=platform.platform(),python=platform.python_version(),device='cpu',cache='no response cache',
                                 threads=torch.get_num_threads(),cpu=platform.processor() or platform.machine(),logical_cpus=os.cpu_count(),
                                 python_hash_seed=os.getenv('PYTHONHASHSEED'),omp_num_threads=os.getenv('OMP_NUM_THREADS'),ram='unmeasured',
                                 packages={name:importlib.metadata.version(name) for name in ['torch','numpy','fastapi','faiss-cpu','httpx']}),
                data_fingerprint=data['manifest']['generation_fingerprint'],
                source_hashes={name:file_hash(Path(name)) for name in ['src/recommendation/bench_ranking.py','src/recommendation/recommender.py','src/recommendation/scoring.py','src/recommendation/service.py']})
    output=output or Path(cfg['paths']['results_dir'])/f'ranking_latency_{cfg["scale"]}_{"b5" if b5 else "b4"}.json'
    write_json(output,report); print(f'{report["stage"]} native={report["native"]}; ASGI HTTP={report["asgi_http"]}; result={output}',flush=True)
    return report


def apply_selection(cfg: dict,selection_path: Path) -> dict:
    selected=json.loads(selection_path.read_text())
    if selected['status']!='SELECTED': raise ValueError('eligible frozen valid policy required')
    for name,digest in selected['source_hashes'].items():
        if file_hash(Path(name))!=digest: raise ValueError(f'frozen source changed: {name}')
    cfg['recommend']['scoring']=selected['selected']['policy']
    return cfg


def main() -> int:
    parser=argparse.ArgumentParser();parser.add_argument('--b4',action='store_true')
    parser.add_argument('--policy',choices=['ctr_cvr','ctr','rank_fusion'])
    parser.add_argument('--alpha',type=float,default=.5)
    parser.add_argument('--selection',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--tcp',action='store_true')
    args=parser.parse_args();cfg=load_config()
    if args.selection and args.policy: parser.error('choose selection or explicit policy')
    if args.selection: cfg=apply_selection(cfg,args.selection)
    if args.policy: cfg['recommend']['scoring']=dict(strategy=args.policy,**({'alpha':args.alpha} if args.policy=='rank_fusion' else {}))
    if args.tcp:
        from src.recommendation.bench_tcp import benchmark_tcp
        report=benchmark_tcp(cfg,not args.b4,args.output,args.selection)
        return 1 if report['status']=='FAIL' else 0
    report=benchmark(cfg,not args.b4,args.output);return 0 if report['status']=='PASS' else 1


if __name__=='__main__': raise SystemExit(main())
