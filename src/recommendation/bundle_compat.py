"""Validate the original recommendation snapshot and unchanged candidate scope."""
from __future__ import annotations

import json
from pathlib import Path

from src.common.artifacts import fingerprint


def candidate_scope(recommend: dict) -> dict:
    return {key: recommend.get(key) for key in
            ('candidate', 'candidate_k', 'exclude_purchased', 'evaluation', 'baselines', 'diagnostics')}


def validate_candidate_config(meta: dict, cfg: dict) -> None:
    scoped = meta.get('candidate_scope_fingerprint')
    if scoped is not None:
        if scoped != fingerprint(candidate_scope(cfg['recommend'])):
            raise ValueError('candidate config scope mismatch')
        return
    path = cfg['recommend'].get('candidate_config_snapshot')
    if not path:
        raise ValueError('bundle/recommend config mismatch; original snapshot required')
    original = json.loads(Path(path).read_text())
    if fingerprint(original) != meta['config_fingerprint']:
        raise ValueError('original candidate config snapshot checksum mismatch')
    for key in candidate_scope(original):
        if cfg['recommend'].get(key) != original.get(key):
            raise ValueError(f'candidate config scope mismatch: {key}')


def verify_preservation(path: Path = Path('docs/results/ranking_preservation.json')) -> dict:
    from src.common.artifacts import file_hash
    report = json.loads(path.read_text())
    for name, expected in report['hashes'].items():
        if file_hash(Path(name)) != expected:
            raise ValueError(f'B3b original changed: {name}')
    return report
