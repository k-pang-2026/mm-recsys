"""Immutable version records, validation-only promotion, atomic active pointer and rollback."""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import re

from src.common.artifacts import file_hash, fingerprint, write_json
from src.ct.storage import append_log, file_lock, utc_now

REQUIRED = ('meta.json', 'two_tower.pt', 'feature_vocab_scalers.json', 'item_ids.json',
            'item_index.faiss', 'index_manifest.json', 'ranking/meta.json',
            'ranking/deepfm.pt', 'ranking/features.json', 'session/meta.json',
            'session/session.pt', 'session/item_ids.json')


def bundle_hashes(path: Path) -> dict:
    return {name: file_hash(path / name) for name in REQUIRED}


class ModelRegistry:
    def __init__(self, root: Path, log: Path):
        self.root, self.log = root.resolve(), log
        self.path = self.root / 'registry.json'
        self.lock = self.root / '.registry.lock'

    def read(self) -> dict:
        if not self.path.exists():
            return dict(schema='ct-registry-v1', active=None, versions={}, last_success_seq=0)
        return json.loads(self.path.read_text())

    def record(self, version: str) -> dict:
        value = copy.deepcopy(self.read()['versions'][version])
        value['bundle_path'] = str(self.root / version)
        return value

    def next_version(self) -> str:
        versions = set(self.read()['versions']) | {p.name for p in self.root.glob('v1.*')}
        numbers = [int(v.split('.')[1]) for v in versions if re.fullmatch(r'v1\.\d+', v)]
        return f'v1.{max(numbers, default=-1) + 1}'

    def register(self, version: str, cfg: dict, data_path: Path, metrics: dict,
                 parent: str | None, through_seq: int) -> dict:
        if not re.fullmatch(r'v[1-9]\d*\.\d+', version):
            raise ValueError('invalid model version')
        json.dumps(metrics, allow_nan=False)
        hashes = bundle_hashes(self.root / version)
        with file_lock(self.lock):
            state = self.read()
            if version in state['versions'] or (parent is not None and parent not in state['versions']):
                raise ValueError('version already registered or unknown parent')
            record = dict(version=version, date=utc_now(), parent=parent, status='CANDIDATE',
                          config=copy.deepcopy(cfg), config_fingerprint=fingerprint(cfg),
                          data_path=str(data_path.resolve()), metrics=metrics, hashes=hashes,
                          trained_through_seq=through_seq)
            state['versions'][version] = record
            write_json(self.path, state)
        append_log(self.log, dict(event='registered', version=version, parent=parent, hashes=hashes))
        return record

    def verify(self, version: str) -> dict:
        record = self.record(version)
        if bundle_hashes(self.root / version) != record['hashes']:
            raise ValueError('registered bundle has changed')
        if fingerprint(record['config']) != record['config_fingerprint']:
            raise ValueError('registered configuration has changed')
        return record

    def initialize(self, version: str) -> None:
        self.verify(version)
        with file_lock(self.lock):
            state = self.read()
            if state['active'] is not None:
                raise ValueError('registry already initialized')
            state['active'] = version
            state['versions'][version]['status'] = 'ACTIVE'
            write_json(self.path, state)
        append_log(self.log, dict(event='initialized', version=version))

    def decide(self, version: str, comparison: dict, spec: dict) -> bool:
        self.verify(version)
        metric = spec['promotion_metric']
        before, after = comparison['baseline'].get(metric), comparison['candidate'].get(metric)
        finite = all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                     for v in (before, after))
        promoted = (finite and comparison.get('split') == 'valid'
                    and bool(comparison.get('validation_fingerprint'))
                    and after > before + float(spec['min_improvement'])
                    and after >= float(spec['promotion_floor']))
        comparison = copy.deepcopy(comparison)
        if not finite:
            for side in ('baseline', 'candidate'):
                value = comparison[side].get(metric)
                if isinstance(value, float) and not math.isfinite(value):
                    comparison[side][metric] = None
            comparison['rejection_reason'] = 'nonfinite or missing promotion metric'
        json.dumps(comparison, allow_nan=False)
        with file_lock(self.lock):
            state = self.read(); record = state['versions'][version]
            if record['status'] != 'CANDIDATE' or state['active'] != record['parent']:
                raise ValueError('promotion raced with another active version')
            record['comparison'] = comparison
            record['status'] = 'ACTIVE' if promoted else 'REJECTED'
            if promoted:
                state['versions'][state['active']]['status'] = 'SUPERSEDED'
                state['active'] = version
            # Successful training consumes only its captured watermark, even if validation rejects it.
            state['last_success_seq'] = record['trained_through_seq']
            write_json(self.path, state)
        append_log(self.log, dict(event='promoted' if promoted else 'retained', version=version,
                                  active=self.read()['active'], comparison=comparison))
        return bool(promoted)

    def rollback(self, expected: str, target: str, reason: str) -> None:
        self.verify(target)
        with file_lock(self.lock):
            state = self.read()
            if state['active'] != expected or target == expected:
                raise ValueError('active version changed or rollback target is identical')
            ancestors = set(); cursor = state['versions'][expected]['parent']
            while cursor:
                ancestors.add(cursor); cursor = state['versions'][cursor]['parent']
            if target not in ancestors or state['versions'][target]['status'] not in ('SUPERSEDED', 'ACTIVE'):
                raise ValueError('rollback target must be a previously active ancestor')
            state['versions'][expected]['status'] = 'ROLLED_BACK'
            state['versions'][target]['status'] = 'ACTIVE'
            state['active'] = target
            write_json(self.path, state)
        append_log(self.log, dict(event='rollback', version=expected, active=target, reason=reason))
