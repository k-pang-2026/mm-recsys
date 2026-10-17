"""Chronological CTR/CVR training; select on valid CTR AUC before opening test."""
from __future__ import annotations

import argparse
import copy
import json
import platform
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from src.common.artifacts import file_hash, fingerprint, write_json
from src.common.config import load_config
from src.common.seed import set_seed
from src.evaluation.metrics import auc, logloss
from src.recommendation.datasets import read_data, cutoff_for
from src.recommendation.features import FeatureEncoder
from src.recommendation.deepfm import DeepFM, loss
from src.recommendation.ranking_features import RankingEncoder, HistoryIndex, DENSE_FIELDS
from src.recommendation.ranking_labels import build_labels, read_impressions


def prepare(cfg: dict, split: str = 'valid') -> tuple[dict, dict, dict]:
    data = read_data(cfg['paths']['data_dir'], split)
    impressions = read_impressions(cfg['paths']['data_dir'], data['manifest'])
    available = ['train', 'valid'] + (['test'] if split == 'test' else [])
    events = pd.concat([data[s] for s in available], ignore_index=True)
    labels, diagnostics = {}, {}
    for name in available:
        boundary = data['manifest']['boundaries'][name]
        labels[name], diagnostics[name] = build_labels(impressions, events[events.timestamp <= pd.Timestamp(boundary['end'])],
                                                       pd.Timestamp(boundary['start']), pd.Timestamp(boundary['end']),
                                                       cfg['recommend']['ranking']['attribution_seconds'])
    return data, labels, diagnostics


def tensors(labels: pd.DataFrame, sparse: np.ndarray, dense: np.ndarray) -> dict:
    return dict(sparse=torch.from_numpy(sparse), dense=torch.from_numpy(dense),
                targets=torch.from_numpy(labels[['ctr','cvr']].to_numpy(np.float32)),
                masks=torch.from_numpy(labels[['ctr_mask','cvr_mask']].to_numpy(np.float32)))


def probabilities(model: DeepFM, values: dict, batch_size: int) -> np.ndarray:
    model.eval(); predictions=[]
    with torch.inference_mode():
        for start in range(0, len(values['sparse']), batch_size):
            predictions.append(model(values['sparse'][start:start+batch_size], values['dense'][start:start+batch_size]).sigmoid().numpy())
    return np.concatenate(predictions)


def measure(values: dict, predictions: np.ndarray) -> dict:
    metrics = {}
    for j, name in enumerate(['ctr','cvr']):
        mask = values['masks'][:,j].numpy().astype(bool)
        y = values['targets'][:,j].numpy()[mask]; p=predictions[mask,j]
        a = auc(y,p) if len(y) else float('nan')
        metrics[name] = dict(auc=float(a) if np.isfinite(a) else None,
                            auc_status='MEASURED' if np.isfinite(a) else 'UNDEFINED_SINGLE_CLASS',
                            logloss=logloss(y,p) if len(y) else None,
                            samples=len(y), positives=int(y.sum()), denominator='observed exposures' if j==0 else 'observed clicked exposures')
    return metrics


def bundle_path(cfg: dict) -> Path:
    return Path(cfg['paths']['model_dir'])/'v1.0'/'ranking'


def load_ranking(cfg: dict, data: dict) -> tuple[DeepFM, RankingEncoder, dict]:
    # C-TEST-003 (docs/contributions/B.md): keep missing/ready/corrupt cases separate;
    # this offline PR does not wire the model into C's serving factory.
    path=bundle_path(cfg); meta=json.loads((path/'meta.json').read_text())
    if meta['data_fingerprint'] != data['manifest']['generation_fingerprint'] or meta['catalog_sha256'] != data['manifest']['file_hashes']['products.parquet']:
        raise ValueError('ranking bundle/data mismatch')
    if meta['config_fingerprint'] != fingerprint(cfg['recommend']['ranking']):
        raise ValueError('ranking config mismatch')
    for name,digest in meta['hashes'].items():
        if file_hash(path/name) != digest: raise ValueError(f'ranking checksum mismatch: {name}')
    encoder=RankingEncoder.from_dict(json.loads((path/'features.json').read_text()))
    if encoder.digest != meta['feature_fingerprint']: raise ValueError('ranking feature fingerprint mismatch')
    model=DeepFM(encoder.cardinalities,len(DENSE_FIELDS),cfg['recommend']['ranking'])
    model.load_state_dict(torch.load(path/'deepfm.pt', map_location='cpu', weights_only=True))
    return model.eval(),encoder,meta


def train(cfg: dict) -> dict:
    started=time.perf_counter(); set_seed(cfg['seed']); spec=cfg['recommend']['ranking']; torch.set_num_threads(spec['threads'])
    data,labels,diagnostics=prepare(cfg)
    for split in ('train','valid'):
        observed=labels[split].loc[labels[split].cvr_mask,'cvr']
        if observed.nunique()!=2:
            raise ValueError(f'{split} CVR requires observed purchases and non-purchases; regenerate a versioned dataset')
    write_json(Path(cfg['paths']['results_dir'])/f'ranking_labels_{cfg["scale"]}.json', diagnostics)
    metadata=FeatureEncoder.fit(data['products'],data['users'],cutoff_for(data,'valid'))
    table=metadata.item_table(data['products']); history=HistoryIndex(data['train'],table)
    encoder=RankingEncoder(metadata,np.zeros(len(DENSE_FIELDS),np.float32),np.ones(len(DENSE_FIELDS),np.float32),spec['cross_features'])
    sparse,dense=encoder.transform(labels['train'],data['users'],table,history,fit=True)
    training=tensors(labels['train'],sparse,dense)
    sparse,dense=encoder.transform(labels['valid'],data['users'],table,history,freeze_at=cutoff_for(data,'valid'))
    validation=tensors(labels['valid'],sparse,dense)
    del labels, history
    model=DeepFM(encoder.cardinalities,len(DENSE_FIELDS),spec)
    optimizer=torch.optim.AdamW(model.parameters(),lr=spec['learning_rate'],weight_decay=spec['weight_decay'])
    generator=torch.Generator().manual_seed(cfg['seed']+4)
    best=-1.; stale=0; state=None; best_epoch=0; epochs=[]
    output=Path(cfg['paths']['results_dir'])/f'ranking_training_{cfg["scale"]}.json'
    for epoch in range(1,spec['epochs']+1):
        tick=time.perf_counter(); model.train(); total=0.; updates=0
        order=torch.randperm(len(training['sparse']),generator=generator)
        for indices in order.split(spec['batch_size']):
            optimizer.zero_grad(set_to_none=True)
            logits=model(training['sparse'][indices],training['dense'][indices])
            value=loss(logits,training['targets'][indices],training['masks'][indices],spec['cvr_loss_weight'])
            if not torch.isfinite(value): raise ValueError('nonfinite DeepFM loss')
            value.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(),10.); optimizer.step()
            total+=float(value.detach())*len(indices); updates+=1
        metrics=measure(validation, probabilities(model,validation,spec['batch_size']))
        score=metrics['ctr']['auc']
        if score is None: raise ValueError('undefined valid CTR AUC')
        epochs.append(dict(epoch=epoch,loss=total/len(order),valid=metrics,updates=updates,seconds=time.perf_counter()-tick))
        print(f'epoch={epoch} loss={epochs[-1]["loss"]:.5f} valid_ctr_auc={score:.6f} cvr_auc={metrics["cvr"]["auc"]}',flush=True)
        if score>best:
            best=score; best_epoch=epoch; stale=0; state=copy.deepcopy(model.state_dict())
        else: stale+=1
        write_json(output,dict(status='RUNNING',scale=cfg['scale'],epochs=epochs,best_epoch=best_epoch,labels=diagnostics))
        if stale>=spec['patience']: break
    if state is None:
        raise ValueError("training produced no valid-selected checkpoint")
    model.load_state_dict(state); path=bundle_path(cfg); path.mkdir(parents=True,exist_ok=True)
    torch.save(model.state_dict(),path/'deepfm.pt'); write_json(path/'features.json',encoder.to_dict())
    meta=dict(version='deepfm-bundle-v1',scale=cfg['scale'],best_epoch=best_epoch,selection_split='valid',
              config_fingerprint=fingerprint(spec),feature_fingerprint=encoder.digest,
              data_fingerprint=data['manifest']['generation_fingerprint'],catalog_sha256=data['manifest']['file_hashes']['products.parquet'],
              hashes={name:file_hash(path/name) for name in ['deepfm.pt','features.json']},ranking_score='P(click)*P(purchase|click)')
    write_json(path/'meta.json',meta)
    loaded,_,_=load_ranking(cfg,data)
    selected=measure(validation,probabilities(loaded,validation,spec['batch_size']))
    if selected != epochs[best_epoch-1]['valid']: raise ValueError('ranking checkpoint reload differs')
    report=dict(status='PASS',acceptance='UNMEASURED',scale=cfg['scale'],labels=diagnostics,epochs=epochs,best_epoch=best_epoch,
                selected_valid=selected,checkpoint_reload='PASS',bundle=meta,elapsed_seconds=time.perf_counter()-started,
                evaluation='valid features/history frozen at train_end; train features strictly before exposure; no test read',
                environment=dict(python=platform.python_version(),torch=torch.__version__,device='cpu',threads=torch.get_num_threads()))
    write_json(output,report)
    write_json(Path(cfg['paths']['results_dir'])/f'ranking_selection_{cfg["scale"]}.json',dict(selection_split='valid',
               best_epoch=best_epoch,model_sha256=meta['hashes']['deepfm.pt'],config_fingerprint=meta['config_fingerprint'],selected_valid=selected))
    return report


def main() -> int:
    parser=argparse.ArgumentParser(); parser.parse_args(); train(load_config()); return 0


if __name__=='__main__': raise SystemExit(main())
