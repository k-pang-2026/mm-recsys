"""Measure B8 search/recommendation/store/API with one explicit provenance record."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from src.common.artifacts import file_hash, fingerprint, write_json
from src.common.config import load_config
from src.common.seed import set_seed
from src.evaluation.reporting import VERSION, environment, identity, metric, sources

MEASUREMENT_SOURCES = ['src/evaluation/run_all.py', 'src/evaluation/reporting.py',
    'src/evaluation/search.py', 'src/evaluation/recommendation.py', 'src/evaluation/api_benchmark.py',
    'src/evaluation/metrics.py', 'src/evaluation/bench_latency.py']


def input_identity(cfg: dict) -> dict:
    """Freeze config and all completed model manifests before test outcomes open."""
    data = Path(cfg['paths']['data_dir'])
    model = Path(cfg['paths']['model_dir'])
    names = [model / 'v1.0/meta.json', model / 'v1.0/ranking/meta.json', model / 'v1.0/session/meta.json',
             model / cfg['search'].get('artifact_subdir', 'search') / 'embeddings_current.json',
             model / cfg['search'].get('artifact_subdir', 'search') / 'indexes_current.json']
    candidate_path = cfg['recommend'].get('candidate_bundle')
    if candidate_path:
        names[0] = Path(candidate_path) / 'meta.json'
    code = MEASUREMENT_SOURCES + sorted(str(p) for directory in ('src/search', 'src/recommendation', 'src/common', 'src/serving') for p in Path(directory).glob('*.py'))
    return dict(config_fingerprint=fingerprint(cfg), data_manifest_sha256=file_hash(data / 'split_manifest.json'),
                models={str(path): file_hash(path) for path in names}, source_hashes=sources(code))


def check_frozen(selection: dict, current: dict, root: Path = Path('.')) -> None:
    if selection.get('selected_on') != 'valid' or selection.get('identity') != current:
        raise ValueError('test requires unchanged valid-frozen data/models/config/source')
    source = root / selection['source']
    if not source.resolve().is_relative_to(root.resolve()):
        raise ValueError('valid measurement source must stay within the repository')
    if file_hash(source) != selection['sha256']:
        raise ValueError('valid measurement changed after evaluation freeze')


def ab_evidence(cfg: dict, manifest: dict, models: dict) -> dict:
    path = Path(cfg['paths']['results_dir']) / 'ab_test.json'
    if not path.exists():
        return dict(status='UNMEASURED', reason='run B7 A/B simulation first')
    report = json.loads(path.read_text())
    if (report['identity']['data_fingerprint'] != manifest['generation_fingerprint'] or report['seed'] != cfg['seed']
            or report['strategies'] != {name: cfg['serving']['ab_test'][name] for name in ('control', 'treatment')}
            or report['outcome_model']['parameters'] != cfg['serving']['ab_test']['outcome']
            or report['days'] != cfg['serving']['ab_test']['days'] or report['top_n'] != cfg['serving']['ab_test']['top_n']):
        raise ValueError('B7 result does not match the current A/B experiment scope')
    for kind in ('candidate', 'ranking', 'session'):
        if report['identity']['bundle_metadata'][kind]['hashes'] != models[kind]['hashes']:
            raise ValueError('B7 result uses different recommendation models')
    for name, digest in report['identity']['source_hashes'].items():
        if file_hash(Path(name)) != digest:
            raise ValueError(f'B7 source changed: {name}')
    return dict(status='MEASURED', source=str(path), sha256=file_hash(path), days=report['days'],
                strategies=report['strategies'], denominators=report['denominators'], inference=report['inference'],
                arms={name: {k: v for k, v in row.items() if k != 'arm_statistics'} for name, row in report['arms'].items()},
                limitations=report['limitations'])


def metric_rows(cfg: dict, split: str, search: dict, rec: dict, api: dict,
                candidate_latency: dict, feature: dict) -> list[dict]:
    rows = [metric(key, search.get('primary', {}).get(key), cfg, split, 'search.primary')
            for key in ('mrr', 'ndcg_at_10')]
    rows.append(metric('recall_at_300', rec.get('candidate', {}).get('ann_two_tower', {}).get('recall_at_300'), cfg, split, 'recommendation.candidate.ann_two_tower'))
    rows.append(metric('auc', rec.get('classification', {}).get('ctr', {}).get('auc'), cfg, split, 'recommendation.classification.ctr', 'single-class or missing CTR labels'))
    rows.extend(metric(key, rec.get('metrics', {}).get('full_pipeline', {}).get(key), cfg, split, 'recommendation.metrics.full_pipeline')
                for key in ('hit_rate_at_50', 'ndcg_at_50', 'coverage'))
    modes = api.get('modes', {})
    values = [modes.get(mode, {}).get('http', {}).get('p95_ms') for mode in ('text', 'image', 'hybrid')]
    rows.extend([
        metric('search_p95_ms', max(values) if all(v is not None for v in values) else None, cfg, 'benchmark', 'api.modes; worst-mode HTTP p95'),
        metric('recommend_p95_ms', modes.get('recommendation', {}).get('http', {}).get('p95_ms'), cfg, 'benchmark', 'api.modes.recommendation.http'),
        metric('candidate_p95_ms', candidate_latency.get('p95_ms'), cfg, 'benchmark', 'candidate_latency'),
        metric('feature_p95_ms', feature.get('latency_ms', {}).get('p95'), cfg, 'benchmark', 'feature_store'),
    ])
    return rows


def run(cfg: dict, split: str, output: Path | None = None) -> dict:
    if os.getenv('PYTHONHASHSEED') != str(cfg['seed']):
        raise ValueError('set PYTHONHASHSEED before starting Python')
    if cfg['benchmark']['warmup'] < 10 or cfg['benchmark']['requests'] < 100 or cfg['benchmark']['concurrency'] != 1:
        raise ValueError('configured serial benchmark requires >=10 warmups and >=100 requests')
    set_seed(cfg['seed'])
    root = Path(cfg['paths']['results_dir'])
    output = output or root / f'evaluation_{cfg["scale"]}_{split}.json'
    frozen_path = root / f'evaluation_selection_{cfg["scale"]}.json'
    inputs = input_identity(cfg)
    if split == 'test':
        check_frozen(json.loads(frozen_path.read_text()), inputs)
    manifest = json.loads((Path(cfg['paths']['data_dir']) / 'split_manifest.json').read_text())
    from src.evaluation.search import evaluate as evaluate_search
    from src.evaluation.recommendation import evaluate as evaluate_recommendation
    from src.evaluation.api_benchmark import benchmark as benchmark_api
    from src.recommendation.bench_candidate import benchmark as benchmark_candidate
    from src.evaluation.bench_latency import benchmark as benchmark_features
    from src.serving.feature_store import RedisFeatureStore, create_feature_store
    from src.serving.warmup_features import warmup
    search = evaluate_search(cfg, split)
    rec = evaluate_recommendation(cfg, split)
    candidate_path = Path(cfg['recommend'].get('candidate_bundle', Path(cfg['paths']['model_dir']) / 'v1.0'))
    candidate_latency = benchmark_candidate(cfg, candidate_path, split)
    store = create_feature_store(cfg)
    if not isinstance(store, RedisFeatureStore):
        raise ValueError('B8 measured Redis is required')
    try:
        warmup(cfg, store)
        feature = benchmark_features(cfg, store)
    finally:
        store.close()
    api = benchmark_api(cfg)
    ab = ab_evidence(cfg, manifest, rec['models'])
    metrics = metric_rows(cfg, split, search, rec, api, candidate_latency, feature)
    quality = 'FAIL' if any(row['status'] == 'FAIL' for row in metrics) else 'UNMEASURED' if any(row['status'] == 'UNMEASURED' for row in metrics) else 'PASS'
    report = dict(version=VERSION, status='PASS', quality_status=quality, acceptance='UNMEASURED',
        scale=cfg['scale'], split=split, identity=identity(cfg, manifest, dict(search=search['models'], recommendation=rec['models'])),
        data_counts=manifest['counts'], source_hashes=inputs['source_hashes'], metrics=metrics,
        search=search, recommendation=rec, candidate_latency=candidate_latency, feature_store=feature,
        api=api, ab=ab, model_version=rec['models']['candidate'].get('model_version', 'unknown'),
        environment=environment(), limitations=['dev/valid is not full test acceptance',
            'CT lifecycle and Compose reproduction are not measured by this evaluator',
            'offline recommendation uses the B5 adapter; live Redis attribution requires separate execution evidence'],
        evaluation_fingerprint=fingerprint(dict(version=VERSION, split=split, inputs=inputs)),
        test_used_for_selection=False)
    if cfg['scale'] == 'full' and split == 'test' and quality == 'FAIL':
        report['acceptance'] = 'FAIL'
    write_json(output, report)
    if split == 'valid':
        # Immutable measurement snapshot keeps past test provenance valid when
        # the display report is refreshed (latency samples vary between runs).
        digest = file_hash(output)
        snapshot = root / 'experiments' / 'C' / 'evaluation_freezes' / f'{digest}.json'
        write_json(snapshot, report)
        write_json(frozen_path, dict(selected_on='valid', identity=inputs, source=str(snapshot), sha256=digest,
                                    scope='measurement recipe freeze; no C tuning or model/policy selection'))
    for row in metrics:
        print(f'{row["name"]}: {row["value"]} / target={row["target"]} / {row["status"]}', flush=True)
    print(f'B8 result: {output}; structure=PASS quality={quality} final_acceptance={report["acceptance"]}', flush=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--split', choices=['valid', 'test'], default='valid')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    run(load_config(), args.split, args.output)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
