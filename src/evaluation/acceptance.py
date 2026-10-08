"""Check measured full-scale acceptance without trusting a handwritten PASS flag."""
from __future__ import annotations

import math
from pathlib import Path
from src.common.artifacts import file_hash


def validate_acceptance(report: dict, cfg: dict, manifest: dict, root: Path) -> None:
    if cfg['scale'] != 'full' or report.get('scale') != 'full' or report.get('status') != 'PASS':
        raise ValueError('measured full-scale PASS report required')
    if manifest.get('scale') != 'full' or report.get('data_fingerprint') != manifest.get('generation_fingerprint'):
        raise ValueError('acceptance dataset fingerprint mismatch')
    for key, minimum in [('products',50000),('users',10000),('events',1000000)]:
        if manifest['counts'].get(key,0) < minimum:
            raise ValueError(f'full dataset too small: {key}')
    metrics=report.get('metrics',{})
    for key, target in {**cfg['targets'],'candidate_count':300}.items():
        entry=metrics.get(key,{})
        value=entry.get('value')
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
            raise ValueError(f'missing/invalid measured metric: {key}')
        if (value > target if key.endswith('_ms') else value < target):
            raise ValueError(f'metric below acceptance target: {key}={value}, target={target}')
        expected_split='benchmark' if key.endswith('_ms') else 'test'
        if entry.get('split') != expected_split or entry.get('status') != 'PASS':
            raise ValueError(f'metric lacks frozen test/benchmark evidence: {key}')
        _verify_source(entry,root)
    checks=report.get('checks',{})
    for key in ['docker_reproduction','api_schemas','ab_statistics','session_response','ct_retrain_and_rollback','submission']:
        entry=checks.get(key,{})
        if entry.get('status') != 'PASS' or entry.get('exit_code') != 0:
            raise ValueError(f'unverified required check: {key}')
        _verify_source(entry,root)


def _verify_source(entry: dict, root: Path) -> None:
    name=entry.get('source');digest=entry.get('sha256')
    if not isinstance(name,str) or not isinstance(digest,str):
        raise ValueError('measured evidence requires source path and sha256')
    path=root/name
    if Path(name).is_absolute() or not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('invalid acceptance source path')
    if file_hash(path) != digest:
        raise ValueError(f'acceptance source changed after measurement: {name}')
