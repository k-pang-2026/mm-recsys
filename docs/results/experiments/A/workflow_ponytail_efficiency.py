"""Compare identical train inputs against the pre-optimization commit.

PYTHONPATH=. .venv/bin/python docs/results/experiments/A/workflow_ponytail_efficiency.py \
    --config <existing-dataset-config.yaml> --output <result.json>
Uses train/valid only. Run with OMP/MKL/OPENBLAS_NUM_THREADS=1 for the recorded setup.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time
import types

import numpy as np
import torch
from torch.utils.data import BatchSampler, DataLoader, RandomSampler

from src.common.artifacts import file_hash, write_json
from src.common.config import load_config
from src.recommendation.datasets import TrainingDataset, cutoff_for, read_data
from src.recommendation.features import FeatureEncoder
from src.recommendation.train_session import examples

BASE = '4e157d3b50473a8c773a24072497063fa91f8437'


def baseline(path: str, name: str) -> types.ModuleType:
    source = subprocess.check_output(['git', 'show', f'{BASE}:{path}'], text=True)
    module = types.ModuleType(name)
    sys.modules[name] = module
    exec(compile(source, path, 'exec'), module.__dict__)
    return module


def run(config: str) -> dict:
    cfg = load_config(config)
    torch.set_num_threads(4)
    data = read_data(cfg['paths']['data_dir'], 'valid')
    encoder = FeatureEncoder.fit(data['products'], data['users'], cutoff_for(data, 'valid'))
    table = encoder.item_table(data['products'])
    old_data = baseline('src/recommendation/datasets.py', 'ponytail_before_data')
    old_session = baseline('src/recommendation/train_session.py', 'ponytail_before_session')
    timings: dict[str, list[list[float]]] = {key: [[], []] for key in ('dataset', 'session', 'batch_loading')}
    for trial in range(3):
        values = {}
        for version in ([0, 1] if trial % 2 == 0 else [1, 0]):
            before = time.perf_counter()
            constructor = old_data.TrainingDataset if version == 0 else TrainingDataset
            values[version] = constructor(data['train'], data['users'], encoder, table, cfg)
            timings['dataset'][version].append(time.perf_counter() - before)
        left, right = values[0], values[1]
        for key in ('history', 'demographics', 'profile', 'items', 'weights'):
            assert torch.equal(getattr(left, key), getattr(right, key)), key
        for key in ('timestamps', 'latest_history'):
            assert np.array_equal(getattr(left, key), getattr(right, key)), key
        assert left.event_ids == right.event_ids and left.diagnostics == right.diagnostics
        session_values = {}
        for version in ([0, 1] if trial % 2 == 0 else [1, 0]):
            before = time.perf_counter()
            function = old_session.examples if version == 0 else examples
            session_values[version] = function(data['train'], table, cfg['recommend']['session']['max_length'],
                data['train'].timestamp.min(), data['train'].timestamp.max())
            timings['session'][version].append(time.perf_counter() - before)
        assert all(np.array_equal(a, b) for a, b in zip(session_values[0], session_values[1]))
        generators = [torch.Generator().manual_seed(cfg['seed'] + 2) for _ in range(2)]
        batch_size = cfg['recommend']['candidate']['batch_size']
        loaders = [DataLoader(left, batch_size=batch_size, shuffle=True, generator=generators[0]),
            DataLoader(right, batch_size=None, generator=generators[1],
                sampler=BatchSampler(RandomSampler(right, generator=generators[1]), batch_size, False))]
        batches = {}
        for version in ([0, 1] if trial % 2 == 0 else [1, 0]):
            before = time.perf_counter()
            batches[version] = [batch for _ in range(3) for batch in loaders[version]]
            timings['batch_loading'][version].append(time.perf_counter() - before)
        assert len(batches[0]) == len(batches[1])
        assert all(torch.equal(a[key], b[key]) for a, b in zip(batches[0], batches[1]) for key in a)
        assert torch.equal(generators[0].get_state(), generators[1].get_state())
    results = {}
    for key, (before, after) in timings.items():
        old, new = statistics.median(before), statistics.median(after)
        results[key] = dict(before_seconds=old, after_seconds=new, speedup=old/new,
            reduction_percent=(1-new/old)*100, raw_before_seconds=before, raw_after_seconds=after)
    cpu = next((line.split(':', 1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines()
                if line.startswith('model name')), platform.processor()) if Path('/proc/cpuinfo').exists() else platform.processor()
    return dict(status='PASS', baseline_commit=BASE, same_outputs_and_shuffle=True,
        data_fingerprint=data['manifest']['generation_fingerprint'], train_rows=len(data['train']),
        training_samples=len(left), repeats=3, statistic='median; alternating before/after order',
        measurements=results, environment=dict(cpu=cpu, python=platform.python_version(),
            torch=torch.__version__, torch_threads=torch.get_num_threads(),
            env_threads={k: os.getenv(k) for k in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS')}),
        source_hashes={name: file_hash(Path(name)) for name in ('src/recommendation/datasets.py',
            'src/recommendation/train_session.py', 'src/recommendation/train_two_tower.py')},
        limits=['compact train data CPU microbenchmark; not HTTP or full-training speedup',
                'concurrent full Docker training on the same host; repeat on target hardware'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.config)
    write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
