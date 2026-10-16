"""Recheck B10 raw measurements and artifact hashes without asserting final acceptance."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from src.common.artifacts import file_hash, write_json
from src.common.config import load_config
from docker.runtime import runtime_config


def local_path(name: str) -> Path:
    path = Path(name)
    if path.is_absolute():
        # Python records __file__ in the container's /app checkout.
        path = path.relative_to('/app')
    if not path.resolve().is_relative_to(Path.cwd().resolve()):
        raise ValueError('measurement source must stay within the checkout')
    return path


def verify(cfg: dict, smoke: dict, preparation: dict, manifest: dict) -> None:
    if smoke.get('status') != 'PASS' or preparation.get('status') != 'PASS':
        raise ValueError('successful smoke and preparation are required')
    if smoke.get('scale') != cfg['scale'] or preparation.get('scale') != cfg['scale']:
        raise ValueError('scale mismatch')
    expected = manifest['generation_fingerprint']
    if smoke.get('data_fingerprint') != expected or preparation.get('data_fingerprint') != expected:
        raise ValueError('data fingerprint mismatch')
    if any(row.get('exit_code') != 0 for row in preparation['stages']) or len(preparation['stages']) != 5:
        raise ValueError('all five preparation stages must succeed')
    if any(smoke.get('checks', {}).get(k) != 'PASS' for k in
           ('api_schemas', 'multipart', 'invalid_search', 'session_response', 'dashboard_http')):
        raise ValueError('missing smoke contract checks')
    bench = smoke['benchmark']
    if not bench['environment']['docker']:
        raise ValueError('container measurements required')
    for name in ('text', 'image', 'hybrid', 'recommendation'):
        row = bench['modes'][name]
        values = row['http_samples_ms']
        if row['warmup'] < 10 or row['requests'] < 100 or len(values) != row['requests'] or row['errors'] != 0:
            raise ValueError('insufficient serial measurement samples')
        actual = float(np.percentile(values, 95))
        target = cfg['targets']['recommend_p95_ms' if name == 'recommendation' else 'search_p95_ms']
        if not np.isfinite(values).all() or abs(actual - row['http']['p95_ms']) > 1e-8 or actual > target:
            raise ValueError(f'{name} latency mismatch or target failure')
    feature = bench['feature']
    if feature['warmup'] < 10 or feature['requests'] < 100 or len(feature['samples_ms']) != feature['requests']:
        raise ValueError('insufficient Redis samples')
    if not np.isfinite(feature['samples_ms']).all() or float(np.percentile(feature['samples_ms'], 95)) > cfg['targets']['feature_p95_ms']:
        raise ValueError('Redis latency failure')
    candidate = bench['candidate']
    if candidate['warmup'] < 10 or candidate['calls'] < 100 or len(candidate['elapsed_ms']) != candidate['calls']:
        raise ValueError('insufficient candidate samples')
    if candidate['candidate_count_min'] < cfg['recommend']['candidate_k'] or not np.isfinite(candidate['elapsed_ms']).all() or float(np.percentile(candidate['elapsed_ms'], 95)) > cfg['targets']['candidate_p95_ms']:
        raise ValueError('candidate count or latency failure')
    for row in (feature, candidate):
        if row['data_fingerprint'] != expected:
            raise ValueError('benchmark dataset mismatch')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--smoke', type=Path)
    args = parser.parse_args(); cfg = runtime_config(load_config())
    smoke_path = args.smoke or Path(f"docs/results/docker/smoke_{cfg['scale']}.json")
    prep_path = smoke_path.parent / f"preparation_{cfg['scale']}.json"
    manifest_path = Path(cfg['paths']['data_dir']) / 'split_manifest.json'
    smoke, prep, manifest = [json.loads(path.read_text()) for path in (smoke_path, prep_path, manifest_path)]
    verify(cfg, smoke, prep, manifest)
    manifest_hash = file_hash(manifest_path)
    if smoke['manifest_sha256'] != manifest_hash or prep['manifest_sha256'] != manifest_hash:
        raise ValueError('data manifest changed after measurement')
    for group in ('models', 'source_hashes'):
        for name, digest in smoke[group].items():
            if file_hash(local_path(name)) != digest:
                raise ValueError(f'measurement input changed: {name}')
            if group == 'models':
                meta_path = local_path(name)
                metadata = json.loads(meta_path.read_text())
                for mapping in ('hashes', 'files'):
                    for child, expected in metadata.get(mapping, {}).items():
                        if not (meta_path.parent / child).resolve().is_relative_to(meta_path.parent.resolve()):
                            raise ValueError('model manifest path escapes its bundle')
                        if file_hash(meta_path.parent / child) != expected:
                            raise ValueError(f'model file changed: {child}')
                if 'index_sha256' in metadata and file_hash(meta_path.parent / 'item_index.faiss') != metadata['index_sha256']:
                    raise ValueError('candidate index changed')
    paths = [smoke_path, prep_path, manifest_path]
    result = dict(status='PASS', scale=cfg['scale'], acceptance='UNMEASURED',
        data_fingerprint=manifest['generation_fingerprint'],
        sources={str(p): file_hash(p) for p in paths},
        scope='Docker preparation, API/store/candidate latency and smoke only; full-test quality separate')
    output = smoke_path.parent / f"verified_{cfg['scale']}.json"
    write_json(output, result)
    print(f'B10 measurement evidence PASS: {output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
