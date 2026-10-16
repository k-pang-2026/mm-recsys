"""Use C's fixed evaluation contracts, with A-owned full Docker quality evidence."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time

from src.common.artifacts import file_hash, write_json
from src.common.seed import set_seed
from src.evaluation.run_all import input_identity, check_frozen, metric_rows
from src.evaluation.reporting import VERSION, environment
from docker.runtime import runtime_config


def run(cfg: dict, split: str) -> dict:
    if os.getenv('PYTHONHASHSEED') != str(cfg['seed']):
        raise ValueError('set PYTHONHASHSEED before starting Python')
    started = time.perf_counter()
    root = Path('docs/results/docker')
    inputs = input_identity(cfg)
    inputs['docker_sources'] = {str(p): file_hash(p) for p in
        (Path('docker/quality.py'), Path('docker/runtime.py'), Path('docker/serve.py'), Path('docker-compose.yml'))}
    selection = root / f"quality_selection_{cfg['scale']}.json"
    if split == 'test':
        check_frozen(json.loads(selection.read_text()), inputs)
    set_seed(cfg['seed'])
    smoke_path = root / f"smoke_{cfg['scale']}.json"
    smoke = json.loads(smoke_path.read_text())
    if smoke['status'] != 'PASS' or smoke['scale'] != cfg['scale']:
        raise ValueError('matching successful Docker latency/smoke evidence required first')
    for path, digest in smoke['models'].items():
        if file_hash(Path(path)) != digest:
            raise ValueError('smoke and quality models differ')
    from src.evaluation.search import evaluate as search_eval
    from src.evaluation.recommendation import evaluate as recommend_eval
    search = search_eval(cfg, split)
    recommendation = recommend_eval(cfg, split)
    bench = smoke['benchmark']
    api = dict(modes=bench['modes'])
    rows = metric_rows(cfg, split, search, recommendation, api, bench['candidate'], bench['feature'])
    counts_ok = recommendation['candidate']['ann_two_tower']['candidate_count_min'] >= cfg['recommend']['candidate_k']
    quality = ('FAIL' if any(row['status'] == 'FAIL' for row in rows) or not counts_ok
               or recommendation['feasible_constraint_violations'] else
               'UNMEASURED' if any(row['status'] == 'UNMEASURED' for row in rows) else 'PASS')
    manifest_path = Path(cfg['paths']['data_dir']) / 'split_manifest.json'
    manifest = json.loads(manifest_path.read_text())
    measured_environment = environment()
    measured_environment['benchmark_scope'] = 'quality evaluator inside CPU Docker container; separate deployed HTTP latency evidence'
    measured_environment['docker_allocation'] = {name: Path('/sys/fs/cgroup', name).read_text().strip()
        for name in ('memory.max', 'cpu.max') if Path('/sys/fs/cgroup', name).is_file()}
    report = dict(version=VERSION, status='PASS', quality_status=quality, acceptance='UNMEASURED', scale=cfg['scale'],
        split=split, identity=inputs, data_fingerprint=manifest['generation_fingerprint'],
        data_counts=manifest['counts'], metrics=rows, candidate_count_pass=counts_ok,
        search=search, recommendation=recommendation, environment=measured_environment,
        api=api, candidate_latency=bench['candidate'], feature_store=bench['feature'],
        ab=dict(status='UNMEASURED', reason='this run has no matching A/B simulation; historical C dev evidence is separate'),
        latency_source=dict(source=str(smoke_path), sha256=file_hash(smoke_path)),
        elapsed_seconds=time.perf_counter()-started, test_used_for_selection=False,
        scope='C fixed-origin quality evaluation on prepared Docker artifacts; latency is measured separately',
        limitations=['not the B11 final acceptance bundle', 'A/B and CT production improvement are separate',
            'recommendation quality uses B5 memory adapter; live Redis MAB exposure/reward attribution remains UNCONNECTED'])
    output = root / f"quality_{cfg['scale']}_{split}.json"
    write_json(output, report)
    write_json(Path(cfg['paths']['results_dir']) / f"evaluation_{cfg['scale']}_{split}.json", report)
    if split == 'valid' and quality == 'PASS':
        # Selection is the unchanged recipe, not a new model/policy tuning step.
        snapshot = root / 'freezes' / f'{file_hash(output)}.json'
        write_json(snapshot, report)
        write_json(selection, dict(selected_on='valid', identity=inputs, source=str(snapshot), sha256=file_hash(snapshot)))
    print(f'Docker quality {split}: {quality}; {output}', flush=True)
    for row in rows:
        print(f"{row['name']}: {row['value']} / {row['target']} / {row['status']}", flush=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--split', choices=['valid', 'test'], required=True)
    parser.add_argument('--verify-existing', action='store_true')
    args = parser.parse_args()
    if os.getenv('DOCKER_RUNTIME') != '1':
        raise ValueError('run quality measurements inside the Docker API image')
    cfg = runtime_config()
    if args.verify_existing:
        result = json.loads(Path(f"docs/results/docker/quality_{cfg['scale']}_{args.split}.json").read_text())
        current = input_identity(cfg)
        current['docker_sources'] = {str(p): file_hash(p) for p in
            (Path('docker/quality.py'), Path('docker/runtime.py'), Path('docker/serve.py'), Path('docker-compose.yml'))}
        if result['identity'] != current:
            raise ValueError('quality data/models/config/source changed')
        if args.split == 'test':
            check_frozen(json.loads(Path(f"docs/results/docker/quality_selection_{cfg['scale']}.json").read_text()), current)
        source = result['latency_source']
        if file_hash(Path(source['source'])) != source['sha256']:
            raise ValueError('quality latency source changed')
        expected = metric_rows(cfg, args.split, result['search'], result['recommendation'], result['api'],
                               result['candidate_latency'], result['feature_store'])
        if expected != result['metrics'] or any(row['status'] != 'PASS' for row in expected):
            raise ValueError('quality metric mismatch or failure')
        if result['recommendation']['candidate']['ann_two_tower']['candidate_count_min'] < cfg['recommend']['candidate_k'] or result['recommendation']['feasible_constraint_violations']:
            raise ValueError('candidate count/constraint failure')
        print(f"Verified Docker quality {args.split}: {result['quality_status']}", flush=True)
    else:
        result = run(cfg, args.split)
    return 0 if result['quality_status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
