"""Verify a scoped classification result and its frozen model/data/source evidence."""
from __future__ import annotations

from src.common.console import log, emit_json, run_cli

import argparse
import json
from pathlib import Path

from src.common.artifacts import file_hash
from src.common.config import load_config
from src.recommendation.bundle_compat import verify_preservation
from src.recommendation.datasets import read_data
from src.recommendation.eval_deepfm import validate_selection
from src.recommendation.train_deepfm import load_ranking


def verify(path: Path, cfg: dict) -> dict:
    report = json.loads(path.read_text())
    if (report['version'] != 'offline-deepfm-classification-v1'
            or report['scale'] != 'full' or cfg['scale'] != 'full'
            or report['split'] != 'test' or report['acceptance'] != 'UNMEASURED'):
        raise ValueError('full frozen test classification evidence required')
    for source, digest in report['sources'].items():
        if file_hash(Path(source)) != digest:
            raise ValueError(f'changed classification source: {source}')
    data = read_data(cfg['paths']['data_dir'], 'test')
    _, _, meta = load_ranking(cfg, data)
    folder = Path(cfg['paths']['results_dir'])
    selection = json.loads((folder/'ranking_selection_full.json').read_text())
    training = json.loads((folder/'ranking_training_full.json').read_text())
    validate_selection(selection, training, meta)
    if (report['data_fingerprint'] != data['manifest']['generation_fingerprint']
            or report['data_counts'] != data['manifest']['counts']
            or report['model_sha256'] != meta['hashes']['deepfm.pt']
            or report['ranking_config_fingerprint'] != meta['config_fingerprint']
            or report['feature_fingerprint'] != meta['feature_fingerprint']
            or report['best_epoch'] != selection['best_epoch']):
        raise ValueError('classification model/data selection changed')
    ctr = report['classification']['ctr']
    if (report['status'] != 'PASS' or ctr['auc'] is None
            or report['ctr_auc_target'] != cfg['targets']['auc']
            or ctr['auc'] < cfg['targets']['auc']):
        raise ValueError('CTR AUC criterion not satisfied')
    verify_preservation()
    log('랭킹', '근거 검사', f'test CTR AUC={ctr["auc"]:.6f} / CVR 한계 유지 / 최종 판정=미측정(UNMEASURED) / B3b 원본 보존', status='통과(PASS)')
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metrics', type=Path, required=True)
    args = parser.parse_args()
    emit_json(verify(args.metrics, load_config()))
    return 0


if __name__ == '__main__':
    raise SystemExit(run_cli(main, '추천 평가', '원본 결과·데이터·모델·설정과 동결된 valid 근거를 확인하세요.'))
