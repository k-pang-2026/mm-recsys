"""Combine measured search evidence without claiming global recommendation acceptance."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import numpy as np
from src.common.artifacts import file_hash, fingerprint, write_json
from src.common.config import load_config
from src.search.build_embeddings import current_bundle


def finalize(cfg: dict) -> dict:
    sources = {'quality': Path(f'docs/results/search_test_{cfg["scale"]}.json'),
               'latency': Path(f'docs/results/search_latency_{cfg["scale"]}.json'),
               'valid_selection': Path(f'docs/results/search_valid_{cfg["scale"]}.json')}
    quality = json.loads(sources['quality'].read_text()); latency = json.loads(sources['latency'].read_text())
    recheck = Path('docs/results/experiments/A/search_http_recheck_full.json')
    if cfg['scale'] == 'full' and recheck.exists():
        observed = json.loads(recheck.read_text())
        for key in ('data_fingerprint', 'model_fingerprint', 'query_manifest_sha256', 'config_fingerprint'):
            if observed[key] != latency[key]:
                raise ValueError('HTTP recheck provenance differs from final benchmark')
        if not observed['target_pass'] or any(value['http']['p95_ms'] > cfg['targets']['search_p95_ms']
                                              for value in observed['per_mode'].values()):
            raise ValueError('final HTTP recheck missed the nominal target')
        sources['http_recheck'] = recheck
    for value in (quality, latency):
        if value['scale'] != cfg['scale'] or value['config_fingerprint'] != fingerprint(cfg):
            raise ValueError('measurement configuration/scale mismatch')
    if quality['split'] != 'test' or quality['test_scores_used_for_selection']:
        raise ValueError('frozen test evaluation must follow valid-only selection')
    if quality['data_fingerprint'] != latency['data_fingerprint'] or quality['model_fingerprint'] != latency['model_fingerprint']:
        raise ValueError('quality and latency use different model/data')
    bundle = current_bundle(cfg)['manifest']
    if (bundle['fingerprint'] != quality['model_fingerprint'] or
            bundle['identity']['data_fingerprint'] != quality['data_fingerprint'] or
            (cfg['scale'] == 'full' and bundle['count'] < 50000)):
        raise ValueError('measurement is not from the current full catalog/model')
    if quality['query_manifest_sha256'] != latency['query_manifest_sha256']:
        raise ValueError('quality/benchmark frozen query provenance differs')
    if latency['concurrency'] != 1 or latency['status'] != 'MEASURED':
        raise ValueError('measured serial HTTP evidence required')
    if set(quality['per_mode']) != {'text', 'image', 'hybrid'} or set(latency['per_mode']) != {'text', 'image', 'hybrid'}:
        raise ValueError('all three fixed query modes required')
    valid_smoke = {value.get('mode') for value in latency['smoke'] if value['status_code'] == 200}
    if valid_smoke != {'text', 'image', 'hybrid', 'multipart_hybrid'} or len([
            value for value in latency['smoke'] if 'invalid_payload' in value]) < 4 or any(
            value['status_code'] != 422 for value in latency['smoke'] if 'invalid_payload' in value):
        raise ValueError('JSON/multipart and invalid-input HTTP evidence required')
    per_mode = {}; targets = cfg['targets']
    for mode, measured in quality['per_mode'].items():
        timing = latency['per_mode'][mode]
        if measured['queries'] != cfg['search']['evaluation']['queries_per_mode']:
            raise ValueError('query cohort size changed')
        for key in ('mrr', 'ndcg_at_10'):
            if not isinstance(measured[key], (int, float)) or not math.isfinite(measured[key]) or not 0 <= measured[key] <= 1:
                raise ValueError('invalid measured quality value')
        samples = timing['http_samples_ms']
        if (len(samples) != cfg['benchmark']['requests'] or timing['requests'] != len(samples) or
                timing['warmup'] != cfg['benchmark']['warmup'] or
                any(not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 for value in samples)):
            raise ValueError('benchmark sample/warmup evidence mismatch')
        if not math.isclose(float(np.percentile(samples, 95)), timing['http']['p95_ms'], abs_tol=1e-6):
            raise ValueError('reported p95 differs from observed HTTP samples')
        passed = (measured['mrr'] >= targets['mrr'] and measured['ndcg_at_10'] >= targets['ndcg_at_10']
                  and timing['http']['p95_ms'] <= targets['search_p95_ms'])
        baseline = quality['bm25'][mode]
        per_mode[mode] = {'quality': measured, 'latency': timing['http'], 'status': 'PASS' if passed else 'FAIL',
                          'bm25': baseline}
        if mode != 'image':
            per_mode[mode]['bm25_relative_change'] = {
                key: (measured[key]/baseline[key]-1) if baseline[key] else None for key in ('mrr', 'ndcg_at_10')}
    primary = quality['primary']
    if primary['queries'] != sum(value['queries'] for value in quality['per_mode'].values()):
        raise ValueError('primary query count mismatch')
    for key in ('mrr', 'ndcg_at_10'):
        mean = float(np.mean([value[key] for value in quality['per_mode'].values()]))
        if not math.isclose(primary[key], mean, abs_tol=1e-10):
            raise ValueError('primary aggregation differs from balanced frozen modes')
    passed = all(value['status'] == 'PASS' for value in per_mode.values())
    metrics = {'mrr': primary['mrr'], 'ndcg_at_10': primary['ndcg_at_10'],
               'search_p95_ms': max(value['latency']['p95_ms'] for value in per_mode.values())}
    result = {'stage': 'B2b', 'scale': cfg['scale'], 'status': 'PASS' if passed else 'FAIL',
              'data_fingerprint': quality['data_fingerprint'], 'model_fingerprint': quality['model_fingerprint'],
              'config_fingerprint': fingerprint(cfg), 'evaluation_fingerprint': quality['evaluation_fingerprint'],
              'split': 'test', 'primary': primary, 'metrics': metrics, 'per_mode': per_mode,
              'sources': {key: {'path': str(path), 'sha256': file_hash(path)} for key, path in sources.items()},
              'checks': {'json_and_multipart_api': 'PASS', 'invalid_inputs_422': 'PASS',
                         'real_http_serial_benchmark': 'PASS', 'valid_only_selection': 'PASS'},
              'query_count': primary['queries'], 'eligible_catalog': quality['eligible_catalog'],
              'global_system_acceptance': 'UNMEASURED',
              'limitations': ['synthetic observable-attribute queries, not real shopper relevance',
                              'BM25 performs better on synthetic text/hybrid queries; negative changes are retained',
                              'image BM25 is not applicable', 'full recommendation and four-service Docker reproduction remain unmeasured']}
    if cfg['scale'] == 'full':
        write_json(Path('docs/results/search_metrics.json'), result)
    write_json(Path(f'docs/results/search_metrics_{cfg["scale"]}.json'), result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-pass', action='store_true'); args = parser.parse_args()
    result = finalize(load_config())
    print(json.dumps({'status': result['status'], 'scale': result['scale'], 'metrics': result['metrics'],
                      'global_system_acceptance': result['global_system_acceptance']}, indent=2))
    if args.require_pass and result['status'] != 'PASS':
        raise SystemExit(2)


if __name__ == '__main__':
    main()
