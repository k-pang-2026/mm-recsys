"""Serial end-to-end candidate benchmark and B3b-specific measured acceptance."""
from __future__ import annotations

import argparse
import json
import os
import platform
import time
from pathlib import Path

import torch
import numpy as np
import pandas as pd

from src.common.artifacts import file_hash, write_json
from src.common.config import load_config
from src.recommendation.candidate import FaissCandidate
from src.recommendation.datasets import context_for, cutoff_for, read_data
from src.recommendation.index import load_index
from src.recommendation.train_two_tower import load_bundle


def benchmark(cfg, bundle: Path, split: str) -> dict:
    spec = cfg['recommend']['candidate']
    from src.recommendation.runtime import configure_inference
    threads = configure_inference(spec, with_faiss=True)
    import faiss
    data = read_data(cfg['paths']['data_dir'], split)
    model, encoder, table, meta = load_bundle(bundle, data, cfg)
    index, manifest = load_index(bundle, table, meta)
    cutoff = cutoff_for(data, split)
    candidate = FaissCandidate(model, table, table.eligible(cutoff), index)
    history = data['train'] if split == 'valid' else pd.concat([data['train'], data['valid']], ignore_index=True)
    groups = {str(uid): group for uid, group in history.groupby('user_id', sort=False)}
    users = data['users'].set_index('user_id').to_dict('index')
    # Fixed request population includes users with no observed history; never sample by future targets.
    ids = sorted(users)
    if not ids:
        raise ValueError('benchmark requires users')
    empty = history.iloc[:0]
    def request(uid):
        context = context_for(groups.get(uid, empty), users[uid], encoder, table, cutoff, spec['history_n'])
        return candidate.retrieve(context), context.history_count
    for i in range(10):
        request(ids[i % len(ids)])
    timings, counts, cold = [], [], 0
    for i in range(100):
        started = time.perf_counter()
        ranked, history_count = request(ids[i % len(ids)])
        timings.append((time.perf_counter() - started) * 1000)
        if len(ranked) != len(set(ranked)):
            raise ValueError('benchmark duplicate candidates')
        counts.append(len(ranked)); cold += int(history_count == 0)
    return dict(scale=cfg['scale'], split='benchmark', context_split=split, cutoff=cutoff.isoformat(),
                warmup=10, calls=100, mode='serial', p50_ms=float(np.percentile(timings, 50)),
                p95_ms=float(np.percentile(timings, 95)), p99_ms=float(np.percentile(timings, 99)),
                candidate_count_min=min(counts), candidate_count_max=max(counts), no_history_calls=cold,
                request_users=ids[:min(100, len(ids))], elapsed_ms=timings,
                includes=['in-memory history/profile lookup', 'timestamp filtering and feature construction',
                          'user tower including history item encoding', 'FAISS HNSW', 'cutoff filtering/refill', 'ID restoration'],
                excludes=['offline index/model load', 'HTTP transport', 'Redis I/O'], cache='no result or user-vector cache',
                data_fingerprint=meta['data_fingerprint'], model_sha256=meta['hashes']['two_tower.pt'],
                config_fingerprint=meta['config_fingerprint'],
                index_sha256=manifest['index_sha256'], environment=dict(python=platform.python_version(),
                torch=torch.__version__, faiss=faiss.__version__, numpy=np.__version__, platform=platform.platform(),
                device='cpu', machine=platform.machine(), cpu_count=os.cpu_count(), threads=threads,
                configured_training_threads=spec['threads'],
                inference_thread_policy='single-thread on macOS ARM for pinned libomp conflict; configured threads elsewhere',
                ram_bytes='UNMEASURED; host resources not exposed by sandbox', gpu_used=False,
                docker_allocation='not applicable; native host benchmark'))


def metrics(evaluation: dict, training: dict, bench: dict) -> dict:
    targets = load_config()['targets']
    exact, ann = evaluation['exact_flat_ip'], evaluation['ann_two_tower']
    counts = evaluation['data_counts']
    matching = (evaluation['model_sha256'] == bench['model_sha256'] == training['bundle']['hashes']['two_tower.pt']
                and evaluation['index_manifest']['index_sha256'] == bench['index_sha256']
                and evaluation['contract']['data_fingerprint'] == bench['data_fingerprint'] == training['contract']['data_fingerprint']
                and evaluation['bundle_meta']['config_fingerprint'] == bench['config_fingerprint'] == training['bundle']['config_fingerprint']
                and evaluation['contract']['cutoff'] == bench['cutoff'])
    checks = dict(full_frozen_test=evaluation['scale'] == bench['scale'] == training['scale'] == 'full'
                  and evaluation['contract']['split'] == bench['context_split'] == 'test'
                  and counts['products'] >= 50000 and counts['users'] >= 10000 and counts['events'] >= 1000000,
                  measured_recall=ann['recall_at_300'] is not None and ann['recall_at_300'] >= targets['recall_at_300'],
                  distinct_300=ann['candidate_count_min'] >= 300 and bench['candidate_count_min'] >= 300,
                  latency=bench['p95_ms'] <= targets['candidate_p95_ms'] and bench['warmup'] == 10 and bench['calls'] == 100,
                  matching_artifacts=matching, valid_selected_checkpoint=training['checkpoint_reload'] == 'PASS',
                  training_integrity=training['status'] == evaluation['status'] == 'PASS'
                  and training['tiny_train_fit']['status'] == 'PASS'
                  and training['sampling']['strictly_preceding_history']
                  and training['sampling']['random_negatives_per_positive'] == 4,
                  exact_reference=exact['candidate_count_min'] >= 300)
    baselines = {name: value['recall_at_300'] for name, value in evaluation['baselines'].items()}
    return dict(stage='B3b', scale=evaluation['scale'], status='PASS' if all(checks.values()) else 'FAIL',
                acceptance='PASS' if all(checks.values()) else 'FAIL', scope='candidate generation only; not final system acceptance',
                checks=checks, contract=evaluation['contract'], data_counts=counts,
                targets={name: targets[name] for name in ['recall_at_300', 'candidate_p95_ms']},
                exact_two_tower=exact, ann_two_tower=ann, baselines=evaluation['baselines'],
                ann_agreement_at_300=evaluation['ann_agreement_at_300'],
                baseline_lift={name: ann['recall_at_300'] / value - 1 if value else None for name, value in baselines.items()},
                checkpoint_selection=dict(seed=training['seed'], best_epoch=training['best_epoch'],
                                          valid_recall_at_300=training['best_valid_exact']['recall_at_300']),
                model_sha256=evaluation['model_sha256'], index_manifest=evaluation['index_manifest'], benchmark=bench,
                environment=evaluation['environment'])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--split', choices=['valid', 'test'], required=True)
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--evaluation', type=Path)
    parser.add_argument('--training', type=Path)
    parser.add_argument('--metrics', type=Path)
    parser.add_argument('--selection', type=Path, help='valid-only frozen selection recorded before test')
    args = parser.parse_args()
    cfg = load_config()
    bundle = args.bundle or Path(cfg['paths']['model_dir']) / 'v1.0'
    result = benchmark(cfg, bundle, args.split)
    write_json(args.output, result)
    print(f"candidate: p95={result['p95_ms']:.3f}ms; count={result['candidate_count_min']}; {args.output}")
    if args.metrics:
        if not args.evaluation or not args.training or not args.selection:
            parser.error('--metrics requires --evaluation, --training and --selection')
        report = metrics(json.loads(args.evaluation.read_text()), json.loads(args.training.read_text()), result)
        report['sources'] = {str(path): file_hash(path) for path in [args.evaluation, args.training, args.output]}
        if args.selection:
            report['sources'][str(args.selection)] = file_hash(args.selection)
        write_json(args.metrics, report)
        print(f"B3b candidate acceptance: {report['status']}; {args.metrics}")
        return 0 if report['status'] == 'PASS' else 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
