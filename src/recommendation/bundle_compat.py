"""Validate the original recommendation snapshot and unchanged candidate scope."""
from __future__ import annotations

import json
from pathlib import Path

from src.common.artifacts import fingerprint


def legacy_training_spec(spec: dict) -> dict:
    """Only the formerly fixed clipping value is equivalent to an absent key."""
    return {key: legacy_training_spec(value) if key in ('candidate', 'ranking', 'session') else value
            for key, value in spec.items() if key != 'max_grad_norm' or value != 10.0}


def training_config_matches(expected: str, spec: dict) -> bool:
    return expected in (fingerprint(spec), fingerprint(legacy_training_spec(spec)))


def candidate_scope(recommend: dict) -> dict:
    return {key: recommend.get(key) for key in
            ('candidate', 'candidate_k', 'exclude_purchased', 'evaluation', 'baselines', 'diagnostics')}


def validate_candidate_config(meta: dict, cfg: dict) -> None:
    scoped = meta.get('candidate_scope_fingerprint')
    if scoped is not None:
        if not training_config_matches(scoped, candidate_scope(cfg['recommend'])):
            raise ValueError('candidate config scope mismatch')
        return
    path = cfg['recommend'].get('candidate_config_snapshot')
    if not path:
        raise ValueError('bundle/recommend config mismatch; original snapshot required')
    original = json.loads(Path(path).read_text())
    if fingerprint(original) != meta['config_fingerprint']:
        raise ValueError('original candidate config snapshot checksum mismatch')
    for key in candidate_scope(original):
        current, previous = cfg['recommend'].get(key), original.get(key)
        if key == 'candidate':
            current, previous = legacy_training_spec(current), legacy_training_spec(previous)
        if current != previous:
            raise ValueError(f'candidate config scope mismatch: {key}')


def verify_preservation(path: Path = Path('docs/results/ranking_preservation.json')) -> dict:
    from src.common.artifacts import file_hash
    report = json.loads(path.read_text())
    for name, expected in report['hashes'].items():
        if file_hash(Path(name)) != expected:
            raise ValueError(f'B3b original changed: {name}')
    return report
