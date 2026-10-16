"""Regenerate a second full dataset and compare every recorded file checksum."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.common.artifacts import file_hash, write_json
from src.common.config import load_config
from src.simulator.generate import generate, GENERATOR_VERSION


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeat-dir', type=Path, default=Path('data/reproduction-full-v41'))
    parser.add_argument('--output', type=Path, default=Path('docs/results/integration/data_reproduction_full.json'))
    args = parser.parse_args()
    cfg = load_config()
    assert cfg['scale'] == 'full'
    source = Path(cfg['paths']['data_dir']) / 'split_manifest.json'
    baseline = json.loads(source.read_text())
    repeated = generate(cfg, args.repeat_dir)
    same = (baseline['generation_fingerprint'] == repeated['generation_fingerprint']
            and baseline['file_hashes'] == repeated['file_hashes']
            and baseline['counts'] == repeated['counts']
            and baseline['boundaries'] == repeated['boundaries'])
    report = dict(status='PASS' if same else 'FAIL', scale='full', generator_version=GENERATOR_VERSION,
        data_fingerprint=baseline['generation_fingerprint'], counts=baseline['counts'],
        original_manifest_sha256=file_hash(source), repeat_manifest_sha256=file_hash(args.repeat_dir / 'split_manifest.json'),
        file_hashes_identical=baseline['file_hashes'] == repeated['file_hashes'],
        original_files=baseline['file_hashes'], repeated_files=repeated['file_hashes'],
        python=platform.python_version(), platform=platform.platform(),
        scope='independent full regeneration in the same pinned Docker environment; images and every parquet/manifest checksum included')
    write_json(args.output, report)
    print(f"Full deterministic regeneration {report['status']}: {args.output}", flush=True)
    return 0 if same else 1


if __name__ == '__main__':
    raise SystemExit(main())
