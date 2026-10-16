"""Register an existing B v1.0 without changing its weights, data or configuration."""
from __future__ import annotations

import argparse
from pathlib import Path

from src.common.config import load_config
from src.common.artifacts import write_json, file_hash
from src.ct.retrain_trigger import components
from src.ct.storage import file_lock
from src.serving.model_loader import load_record
from src.serving.memory_store import MemoryFeatureStore


def bootstrap(cfg: dict) -> dict:
    _, _, registry = components(cfg)
    with file_lock(registry.root / '.ct' / 'training.lock', blocking=False):
        if registry.read()['active']:
            registry.verify(registry.read()['active'])
            return registry.read()
        if 'v1.0' not in registry.read()['versions']:
            registry.register('v1.0', cfg, Path(cfg['paths']['data_dir']),
                              dict(status='UNMEASURED', reason='initial existing bundle; no invented validation'), None, 0)
        load_record(registry, 'v1.0', MemoryFeatureStore())
        registry.initialize('v1.0')
    return registry.read()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    cfg = load_config()
    state = bootstrap(cfg)
    if args.output:
        import json
        _, _, registry = components(cfg)
        record = registry.verify(state['active'])
        manifest_path = Path(record['data_path']) / 'split_manifest.json'
        manifest = json.loads(manifest_path.read_text())
        write_json(args.output, dict(status='PASS', acceptance='UNMEASURED', scale=cfg['scale'],
            seed=cfg['seed'], active=state['active'], data_fingerprint=manifest['generation_fingerprint'],
            data_counts=manifest['counts'], manifest_sha256=file_hash(manifest_path),
            config_fingerprint=record['config_fingerprint'], model_hashes=record['hashes'],
            scope='existing bundle fully loaded and warmed; no production retraining/promotion'))
    print(f"Registered active model: {state['active']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
