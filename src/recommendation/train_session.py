"""Next-view training within recorded session IDs; valid-only checkpoint selection."""
from __future__ import annotations

from typing import Any

import argparse
import copy
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch.nn import functional as F

from src.common.artifacts import file_hash,fingerprint,write_json
from src.common.config import load_config
from src.common.seed import set_seed
from src.recommendation.datasets import read_data
from src.recommendation.train_two_tower import load_bundle
from src.recommendation.session import SessionEncoder


def examples(events: pd.DataFrame,table: Any,max_length: int,start: pd.Timestamp,end: pd.Timestamp) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    inputs=[]; targets=[]; times=[]; latest=[]
    views=events[(events.event_type=='view') & events.product_id.notna()].sort_values(['timestamp','event_id'])
    for _,group in views.groupby(['user_id','session_id'],sort=False):
        history: list[int] = []; last_time: pd.Timestamp | None = None
        for at,simultaneous in group.groupby('timestamp',sort=True):
            if history and start<=at<=end:
                assert last_time is not None
                sequence=np.zeros(max_length,np.int64); recent=history[-max_length:]; sequence[:len(recent)]=recent
                for row in simultaneous.itertuples(index=False):
                    target=table.id_to_index[str(row.product_id)]
                    if table.created[target]>at.value: raise ValueError('session target is future product')
                    inputs.append(sequence.copy()); targets.append(target); times.append(at.value); latest.append(last_time.value)
            history.extend(table.id_to_index[str(p)] for p in simultaneous.product_id); last_time=at
    if not inputs: raise ValueError('no next-view session samples')
    return np.stack(inputs),np.array(targets,np.int64),np.array(times,np.int64),np.array(latest,np.int64)


def negative_items(targets: np.ndarray,times: np.ndarray,table: Any,count: int,seed: int) -> torch.Tensor:
    rng=np.random.default_rng(seed); order=np.argsort(table.created); eligible_times=table.created[order]
    result=np.empty((len(targets),count+1),np.int64); result[:,0]=targets
    for i,(target,at) in enumerate(zip(targets,times)):
        pool=order[:np.searchsorted(eligible_times,at,side='right')]; pool=pool[pool!=target]
        if not len(pool): raise ValueError('no eligible session negatives')
        result[i,1:]=rng.choice(pool,count,replace=len(pool)<count)
    return torch.from_numpy(result)


def session_path(cfg: dict) -> Path: return Path(cfg['paths']['model_dir'])/'v1.0'/'session'


def load_session(cfg: dict,data: dict,table: Any,candidate_meta: dict) -> tuple[SessionEncoder, dict]:
    path=session_path(cfg); meta=json.loads((path/'meta.json').read_text())
    if meta['config_fingerprint']!=fingerprint(cfg['recommend']['session']): raise ValueError('session config mismatch')
    if meta['data_fingerprint']!=data['manifest']['generation_fingerprint'] or meta['candidate_sha256']!=candidate_meta['hashes']['two_tower.pt']:
        raise ValueError('session candidate/data mismatch')
    for name,digest in meta['hashes'].items():
        if file_hash(path/name)!=digest: raise ValueError(f'session checksum mismatch: {name}')
    if json.loads((path/'item_ids.json').read_text())!=table.ids: raise ValueError('session ID mapping mismatch')
    state=torch.load(path/'session.pt',map_location='cpu',weights_only=True)
    model=SessionEncoder(state['items.weight'].numpy(),cfg['recommend']['session']); model.load_state_dict(state)
    return model.eval(),meta


def evaluate(model: SessionEncoder,sequences: torch.Tensor,items: torch.Tensor,batch_size: int,temperature: float) -> dict:
    model.eval(); total=0.; hits=0
    with torch.inference_mode():
        for start in range(0,len(sequences),batch_size):
            vector=model(sequences[start:start+batch_size]); candidates=items[start:start+batch_size]
            logits=torch.einsum('bd,bkd->bk',vector,model.items(candidates))/temperature
            total+=float(F.cross_entropy(logits,torch.zeros(len(vector),dtype=torch.long),reduction='sum'))
            hits+=int((logits.topk(min(10,logits.shape[1]),dim=1).indices==0).any(1).sum())
    return dict(loss=total/len(sequences),sampled_hit_at_10=hits/len(sequences),samples=len(sequences),
                candidates=items.shape[1],denominator='target plus fixed eligible random negatives; not full-catalog HitRate')


def train(cfg: dict) -> dict:
    started=time.perf_counter(); set_seed(cfg['seed']); spec=cfg['recommend']['session']; torch.set_num_threads(cfg['recommend']['ranking']['threads'])
    data=read_data(cfg['paths']['data_dir'],'valid'); candidate,_,table,candidate_meta=load_bundle(Path(cfg['paths']['model_dir'])/'v1.0',data,cfg)
    with torch.inference_mode():
        vectors=candidate.encode_items(torch.arange(len(table.ids))).numpy()
    # Preserve recorded sessions; legacy datasets may differ from the live inactivity TTL.
    boundary=data['manifest']['boundaries']; training=examples(data['train'],table,spec['max_length'],pd.Timestamp(boundary['train']['start']),pd.Timestamp(boundary['train']['end']))
    valid=examples(pd.concat([data['train'],data['valid']],ignore_index=True),table,spec['max_length'],pd.Timestamp(boundary['valid']['start']),pd.Timestamp(boundary['valid']['end']))
    train_seq=torch.from_numpy(training[0]); valid_seq=torch.from_numpy(valid[0])
    negatives=int(spec['negatives']); temperature=float(spec['temperature'])
    train_items=negative_items(training[1],training[2],table,negatives,cfg['seed']+10)
    valid_items=negative_items(valid[1],valid[2],table,negatives,cfg['seed']+11)
    model=SessionEncoder(vectors,spec); optimizer=torch.optim.AdamW(model.parameters(),lr=spec['learning_rate'],weight_decay=spec['weight_decay'])
    generator=torch.Generator().manual_seed(cfg['seed']+12); best=float('inf'); state=None; stale=0; epochs=[]; best_epoch=0
    output=Path(cfg['paths']['results_dir'])/f'session_training_{cfg["scale"]}.json'
    for epoch in range(1,spec['epochs']+1):
        model.train(); total=0.; tick=time.perf_counter()
        for indices in torch.randperm(len(train_seq),generator=generator).split(spec['batch_size']):
            optimizer.zero_grad(set_to_none=True); vector=model(train_seq[indices])
            logits=torch.einsum('bd,bkd->bk',vector,model.items(train_items[indices]))/temperature
            value=F.cross_entropy(logits,torch.zeros(len(indices),dtype=torch.long))
            if not torch.isfinite(value): raise ValueError('nonfinite session loss')
            value.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(),10.); optimizer.step(); total+=float(value.detach())*len(indices)
        metrics=evaluate(model,valid_seq,valid_items,spec['batch_size'],temperature)
        epochs.append(dict(epoch=epoch,loss=total/len(train_seq),valid=metrics,seconds=time.perf_counter()-tick))
        print(f'session epoch={epoch} valid_loss={metrics["loss"]:.5f} sampled_hit@10={metrics["sampled_hit_at_10"]:.5f}',flush=True)
        if metrics['loss']<best:
            best=metrics['loss']; best_epoch=epoch; state=copy.deepcopy(model.state_dict()); stale=0
        else: stale+=1
        write_json(output,dict(status='RUNNING',scale=cfg['scale'],epochs=epochs,best_epoch=best_epoch))
        if stale>=spec['patience']: break
    if state is None:
        raise ValueError("training produced no valid-selected checkpoint")
    model.load_state_dict(state); path=session_path(cfg); path.mkdir(parents=True,exist_ok=True)
    torch.save(model.state_dict(),path/'session.pt'); write_json(path/'item_ids.json',table.ids)
    meta=dict(version='gru-session-v1',best_epoch=best_epoch,selection_split='valid',config_fingerprint=fingerprint(spec),
              candidate_sha256=candidate_meta['hashes']['two_tower.pt'],data_fingerprint=data['manifest']['generation_fingerprint'],
              hashes={name:file_hash(path/name) for name in ['session.pt','item_ids.json']})
    write_json(path/'meta.json',meta); loaded,_=load_session(cfg,data,table,candidate_meta)
    selected=evaluate(loaded,valid_seq,valid_items,spec['batch_size'],temperature)
    if selected!=epochs[best_epoch-1]['valid']: raise ValueError('session checkpoint reload differs')
    report=dict(status='PASS',scale=cfg['scale'],acceptance='UNMEASURED',epochs=epochs,best_epoch=best_epoch,selected_valid=selected,
                checkpoint_reload='PASS',bundle=meta,elapsed_seconds=time.perf_counter()-started,train_samples=len(train_seq),
                strictly_preceding=bool((training[3]<training[2]).all() and (valid[3]<valid[2]).all()),
                semantics='offline recorded session_id; live store inactivity TTL=30min; generator 4.2 uses minute-scale session steps',
                environment=dict(torch=torch.__version__,threads=torch.get_num_threads(),device='cpu'))
    write_json(output,report); return report


def main() -> int:
    argparse.ArgumentParser().parse_args(); train(load_config()); return 0


if __name__=='__main__': raise SystemExit(main())
