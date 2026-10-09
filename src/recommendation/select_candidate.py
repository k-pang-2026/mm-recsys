"""Freeze a valid-only selection before opening test; reproducible B3b handoff."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.common.artifacts import file_hash, write_json
from src.common.config import load_config


def selection(training_path: Path, valid_path: Path, benchmark_path: Path, diagnosis_path: Path, cfg: dict) -> dict:
    training, valid, bench, diagnosis = [json.loads(path.read_text()) for path in
                                         [training_path, valid_path, benchmark_path, diagnosis_path]]
    if (valid['contract']['split'] != 'valid' or bench['context_split'] != 'valid'
            or diagnosis['status'] != 'PASS' or training['checkpoint_reload'] != 'PASS'):
        raise ValueError('selection requires successful valid-only diagnosis and checkpoint reload')
    if (valid['scale'] != training['scale'] or valid['scale'] != bench['scale']
            or valid['scale'] != cfg['scale'] or training['seed'] != cfg['seed']):
        raise ValueError('selection scale/seed mismatch')
    if (valid['model_sha256'] != training['bundle']['hashes']['two_tower.pt']
            or valid['model_sha256'] != bench['model_sha256']
            or valid['index_manifest']['index_sha256'] != bench['index_sha256']
            or valid['contract']['data_fingerprint'] != training['contract']['data_fingerprint']
            or valid['contract']['data_fingerprint'] != bench['data_fingerprint']
            or valid['bundle_meta']['config_fingerprint'] != bench['config_fingerprint']):
        raise ValueError('selection measurement fingerprints mismatch')
    if (valid['ann_two_tower']['recall_at_300'] < cfg['targets']['recall_at_300']
            or bench['p95_ms'] > cfg['targets']['candidate_p95_ms']
            or valid['ann_two_tower']['candidate_count_min'] < 300 or bench['candidate_count_min'] < 300):
        raise ValueError('valid candidate thresholds not met; repair on valid before opening test')
    return dict(stage='B3b', selection_split='valid', seed=training['seed'], best_epoch=training['best_epoch'],
                model_sha256=valid['model_sha256'], config_fingerprint=valid['bundle_meta']['config_fingerprint'],
                data_fingerprint=valid['contract']['data_fingerprint'], index_sha256=valid['index_manifest']['index_sha256'],
                ann_parameters={key: valid['index_manifest'][key] for key in ['M', 'ef_search', 'ef_construction']},
                valid_exact_recall_at_300=valid['exact_flat_ip']['recall_at_300'],
                valid_ann_recall_at_300=valid['ann_two_tower']['recall_at_300'], valid_p95_ms=bench['p95_ms'],
                inference_threads=bench['environment']['threads'],
                decision=f"freeze baseline config and epoch{training['best_epoch']} before first test evaluation; no hyperparameter ablations needed for mandatory thresholds",
                sources={str(path): file_hash(path) for path in [training_path, valid_path, benchmark_path, diagnosis_path]})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify-existing', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('docs/results/candidate_selection.json'))
    args = parser.parse_args()
    cfg = load_config(); folder = Path(cfg['paths']['results_dir']); scale = cfg['scale']
    result = selection(folder / f'candidate_training_{scale}.json', folder / f'candidate_{scale}_valid.json',
                       folder / f'candidate_benchmark_{scale}_valid.json', folder / 'candidate_diagnostics.json', cfg)
    if args.verify_existing:
        if json.loads(args.output.read_text()) != result:
            raise ValueError('frozen selection differs from valid-only sources')
        print(f'valid selection verified: epoch{result["best_epoch"]}; {args.output}')
    else:
        # A frozen result is immutable unless the caller uses a new output/version path.
        if args.output.exists():
            raise ValueError('selection already exists; use --verify-existing or a new version path')
        write_json(args.output, result)
        print(f'valid selection frozen before test: epoch{result["best_epoch"]}; {args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
