"""Recompute B3b acceptance from checksum-bound saved runs, without rerunning training/test."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.common.artifacts import file_hash
from src.common.config import load_config
from src.recommendation.bench_candidate import metrics
from src.recommendation.datasets import read_data
from src.recommendation.index import load_index
from src.recommendation.train_two_tower import load_bundle


def verify(path: Path, cfg: dict) -> dict:
    report = json.loads(path.read_text())
    for source, digest in report['sources'].items():
        if file_hash(Path(source)) != digest:
            raise ValueError(f'changed measurement source: {source}')
    sources = [json.loads(Path(source).read_text()) for source in report['sources']]
    evaluation = next(value for value in sources if 'ann_two_tower' in value)
    training = next(value for value in sources if 'epochs' in value)
    benchmark = next(value for value in sources if 'elapsed_ms' in value)
    selection = next(value for value in sources if value.get('selection_split') == 'valid')
    for source, digest in selection['sources'].items():
        if file_hash(Path(source)) != digest:
            raise ValueError(f'changed valid selection source: {source}')
    if (selection['model_sha256'] != evaluation['model_sha256']
            or selection['index_sha256'] != benchmark['index_sha256']
            or selection['config_fingerprint'] != benchmark['config_fingerprint']
            or selection['data_fingerprint'] != benchmark['data_fingerprint']
            or selection['best_epoch'] != training['best_epoch'] or selection['seed'] != training['seed']):
        raise ValueError('final test differs from frozen valid selection')
    computed = metrics(evaluation, training, benchmark)
    if report != dict(computed, sources=report['sources']):
        raise ValueError('candidate metrics differ from measured sources')
    if report['status'] != 'PASS':
        raise ValueError(f"candidate acceptance failed: {report['checks']}")
    if cfg['scale'] != 'full':
        raise ValueError('candidate verification requires SCALE=full')
    data = read_data(cfg['paths']['data_dir'], 'test')
    if data['manifest']['counts'] != report['data_counts']:
        raise ValueError('reported full counts differ from manifest')
    bundle = Path(cfg['paths']['model_dir']) / 'v1.0'
    _, _, table, meta = load_bundle(bundle, data, cfg)
    _, manifest = load_index(bundle, table, meta)
    if report['model_sha256'] != meta['hashes']['two_tower.pt'] or report['index_manifest'] != manifest:
        raise ValueError('measured model/index differs from current bundle')
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--metrics', type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.metrics, load_config())
    print(f"B3b verified: full test ANN Recall@300={report['ann_two_tower']['recall_at_300']:.6f}; "
          f"p95={report['benchmark']['p95_ms']:.3f}ms; count={report['ann_two_tower']['candidate_count_min']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
