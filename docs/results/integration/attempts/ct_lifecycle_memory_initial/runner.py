"""Separate full-size rollback drill after natural CT retention; never weaken production."""
from __future__ import annotations
import copy
import gc
import json
from pathlib import Path
import shutil
import socket
import sys
import threading
import time
from typing import Any
import uuid
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    import requests
    import torch
    import uvicorn
    from src.common.artifacts import file_hash, fingerprint, write_json
    from src.common.config import load_config
    from src.ct.model_registry import ModelRegistry, bundle_hashes
    from src.ct.retrain_trigger import components, reload_api
    from src.recommendation.datasets import cutoff_for
    from src.recommendation.ranking_features import HistoryIndex
    from src.recommendation.train_deepfm import prepare, tensors, probabilities, measure
    from src.serving.feature_store import RedisFeatureStore
    from src.serving.main import create_app
    from src.serving.memory_store import MemoryFeatureStore
    from src.serving.model_loader import load_record
    cfg=load_config();out=Path('docs/results/integration')
    natural=json.loads((out/'ct_full.json').read_text())
    assert cfg['scale']=='full' and natural['status']=='PARTIAL'
    assert natural['retraining']['status']=='RETAINED' and not natural['real_reload_and_rollback']
    spec,_,production=components(cfg);state=production.read()
    assert state['active']=='v1.0'
    candidate_version=natural['retraining']['version']
    trained=production.verify(candidate_version);initial=production.verify('v1.0')
    assert trained['status']=='REJECTED' and trained['hashes']==json.loads((out/'ct_candidate_valid_full.json').read_text())['bundle_hashes']
    work=production.root/'.ct'/('full-lifecycle-'+uuid.uuid4().hex[:10])
    root=work/'models';root.mkdir(parents=True)
    for version,source in [('v1.0',production.root/'v1.0'),('v1.1',production.root/candidate_version)]:
        shutil.copytree(source,root/version)
    # Fault injection is confined to a NEW INITIAL fixture, before registration.
    # The real active v1.0 and actual trained candidate remain byte-identical.
    rank=root/'v1.0/ranking';weights=torch.load(rank/'deepfm.pt',map_location='cpu',weights_only=True)
    torch.save({key:torch.zeros_like(value) for key,value in weights.items()},rank/'deepfm.pt')
    meta=json.loads((rank/'meta.json').read_text());meta['hashes']['deepfm.pt']=file_hash(rank/'deepfm.pt');write_json(rank/'meta.json',meta)
    fixture_cfg=copy.deepcopy(cfg);fixture_cfg['paths'].update(model_dir=str(root),results_dir=str(work/'results'))
    registry=ModelRegistry(root,work/'lifecycle.jsonl')
    registry.register('v1.0',fixture_cfg,Path(initial['data_path']),{},None,0);registry.initialize('v1.0')
    candidate_cfg=copy.deepcopy(trained['config']);candidate_cfg['paths'].update(model_dir=str(root),results_dir=str(work/'results'))
    registry.register('v1.1',candidate_cfg,Path(trained['data_path']),{},'v1.0',trained['trained_through_seq'])
    data,labels,_=prepare(candidate_cfg,'valid');manifest=data['manifest']
    assert manifest['counts']['products']==50000 and manifest['counts']['users']==10000
    assert manifest['parent_fingerprint']==natural['data_fingerprint']
    at=cutoff_for(data,'valid')
    identity=fingerprint(dict(split='valid',manifest=manifest,contract='paired full mature-exposure CTR; identical labels and fixed train cutoff'))
    values={}
    for side,version in [('baseline','v1.0'),('candidate','v1.1')]:
        service=load_record(registry,version,MemoryFeatureStore())
        history=HistoryIndex(data['train'],service.table)
        sparse,dense=service.ranking_encoder.transform(labels['valid'],data['users'],service.table,history,freeze_at=at)
        batches=tensors(labels['valid'],sparse,dense)
        metric=measure(batches,probabilities(service.ranker,batches,cfg['recommend']['ranking']['batch_size']))['ctr']
        values[side]=dict(ctr_auc=metric['auc'],ctr_logloss=metric['logloss'],ctr_samples=metric['samples'],ctr_positives=metric['positives'],validation_fingerprint=identity)
        del service,history,sparse,dense,batches
        gc.collect()
    assert values['baseline']['ctr_auc']==.5
    assert values['candidate']['ctr_samples']==natural['retraining']['comparison']['candidate']['ctr_samples']
    assert abs(values['candidate']['ctr_auc']-natural['retraining']['comparison']['candidate']['ctr_auc'])<1e-12
    comparison=dict(split='valid',validation_fingerprint=identity,**values)
    write_json(out/'ct_controlled_paired_ctr_full.json',dict(status='PASS',scale='full',comparison=comparison,
        counts=manifest['counts'],scope='identical full valid CTR labels; deliberately constant INITIAL fixture vs exact naturally trained candidate; no test'))
    del data,labels
    gc.collect()
    namespace='mm-recsys:full:ct-lifecycle-'+work.name
    store=RedisFeatureStore(host=cfg['redis']['host'],port=cfg['redis']['port'],namespace=namespace,mab_spec=cfg['recommend']['mab'])
    assert store.client.ping()
    class LiveSearchProxy:
        def search(self,payload: Any) -> Any:
            with requests.Session() as client:
                client.trust_env=False
                response=client.post('http://127.0.0.1:8000/api/search',json=payload.model_dump(),timeout=120)
                response.raise_for_status()
                return response.json()
    app=create_app(fixture_cfg,search_service=LiveSearchProxy(),feature_store=store)
    sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,log_level='warning',proxy_headers=False))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True);thread.start()
    url=f'http://127.0.0.1:{port}';http=[];reloads=[]
    def check(version: str) -> None:
        with requests.Session() as client:
            client.trust_env=False
            health=client.get(url+'/health',timeout=30);health.raise_for_status();assert health.json()['model_version']==version
            for uid in ('U000001','unknown-full-lifecycle'):
                response=client.get(url+'/api/recommend',params={'user_id':uid,'top_n':10},timeout=120)
                response.raise_for_status();assert len(response.json()['recommendations'])==10
                http.append(dict(version=version,user_id=uid,status=response.status_code))
    try:
        for _ in range(1200):
            if server.started:break
            if not thread.is_alive():raise RuntimeError('full fixture API startup failed')
            time.sleep(.05)
        assert server.started
        check('v1.0')
        assert registry.decide('v1.1',comparison,spec),'original .001 improvement/floor guard must pass measured fixture comparison'
        reloads.append(reload_api(url,'v1.1'));check('v1.1')
        registry.rollback('v1.1','v1.0','isolated full functional rollback after measured controlled initial promotion')
        reloads.append(reload_api(url,'v1.0'));check('v1.0')
        assert production.read()['active']=='v1.0'
        assert production.verify('v1.0')['hashes']==initial['hashes']
        assert production.verify(candidate_version)['hashes']==trained['hashes']
        assert bundle_hashes(root/'v1.1')==trained['hashes']
        shutil.copy2(registry.log,out/'ct_controlled_lifecycle_full.jsonl')
        report=dict(status='PASS',scale='full',scenario='controlled_initial_constant_ranker',
            data_fingerprint=natural['data_fingerprint'],counts=manifest['counts'],natural_retraining='RETAINED',
            comparison=comparison,guard=spec,real_reload_and_rollback=True,http=http,reloads=reloads,
            original_candidate_hashes=trained['hashes'],candidate_hashes=bundle_hashes(root/'v1.1'),
            production_unchanged=True,fixture_active=registry.read()['active'],redis_namespace=namespace,
            natural=dict(source=str(out/'ct_full.json'),sha256=file_hash(out/'ct_full.json')),
            lifecycle=dict(source=str(out/'ct_controlled_lifecycle_full.jsonl'),sha256=file_hash(out/'ct_controlled_lifecycle_full.jsonl')),
            source_hashes={str(p):file_hash(p) for p in [*Path('src/ct').glob('*.py'),Path(__file__).relative_to(ROOT)]},
            scope='full-size independent functional promotion/reload/rollback, deliberately weak INITIAL fixture, exact naturally retrained candidate and original guard; production remains naturally RETAINED',
            limitations=['controlled fault injection does not measure production improvement','CTR paired valid comparison; no new test evaluation','not a second training run; exact actual full three-model candidate reused','production initial bundle and registry pointer remain unchanged'])
        write_json(out/'ct_controlled_lifecycle_full.json',report)
        print('Isolated full CT lifecycle PASS; production remains RETAINED',flush=True)
        return 0
    finally:
        server.should_exit=True;thread.join(30);sock.close();store.close()

if __name__=='__main__':
    raise SystemExit(main())
