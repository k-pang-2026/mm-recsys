"""Recreate only the ignored dev/full recommendation bundles needed by B7.

Uses unchanged B-owned trainers/config/seed. Existing incompatible artifacts fail
validation instead of being silently overwritten. Training reports stay in C scope.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path

from src.common.artifacts import write_json
from src.common.config import load_config
from src.recommendation.datasets import read_data
from src.recommendation.index import load_index
from src.recommendation.service import create_service
from src.recommendation.train_deepfm import bundle_path, load_ranking, train as train_ranking
from src.recommendation.train_session import load_session, session_path, train as train_session
from src.recommendation.train_two_tower import load_bundle, train as train_candidate
from src.serving.memory_store import MemoryFeatureStore
from src.simulator.generate import generate


def prepare(cfg: dict) -> dict:
    if os.getenv('PYTHONHASHSEED') != str(cfg['seed']):
        raise ValueError('launch with configured PYTHONHASHSEED')
    if os.getenv('RECOMMEND_MODEL_DIR'):
        raise ValueError('unset RECOMMEND_MODEL_DIR before artifact preparation')
    manifest = generate(cfg)
    output = Path(cfg['paths']['results_dir']) / 'experiments' / 'C' / f'ab_models_{cfg["scale"]}'
    # Report destination is not a training parameter or model fingerprint field.
    cfg = copy.deepcopy(cfg)
    cfg['paths']['results_dir'] = str(output)
    data = read_data(cfg['paths']['data_dir'], 'valid')
    candidate_path = Path(cfg['recommend'].get('candidate_bundle', Path(cfg['paths']['model_dir']) / 'v1.0'))
    if not candidate_path.exists():
        train_candidate(cfg, output / 'candidate_training.json', candidate_path)
    _, _, table, candidate_meta = load_bundle(candidate_path, data, cfg)
    _, index_meta = load_index(candidate_path, table, candidate_meta)
    if not bundle_path(cfg).exists():
        train_ranking(cfg)
    _, _, ranking_meta = load_ranking(cfg, data)
    if not session_path(cfg).exists():
        train_session(cfg)
    _, session_meta = load_session(cfg, data, table, candidate_meta)
    if create_service(cfg, MemoryFeatureStore()) is None:
        raise ValueError('regenerated recommendation service did not load')
    report = dict(status='PASS', scale=cfg['scale'], seed=cfg['seed'],
        data_fingerprint=manifest['generation_fingerprint'], data_hashes=manifest['file_hashes'],
        candidate=candidate_meta, index=index_meta, ranking=ranking_meta, session=session_meta,
        checks='dataset/image hashes; candidate config/dimension/ID mapping/index; ranking/session config/data/model checksums; service load',
        test_outcomes_read=False, acceptance='UNMEASURED',
        portability='same config/seed; model bytes and floating-point results may differ across OS/Python')
    write_json(output / 'compatibility.json', report)
    print(f'Compatible {cfg["scale"]} bundles: {output / "compatibility.json"}', flush=True)
    return report


if __name__ == '__main__':
    prepare(load_config())
