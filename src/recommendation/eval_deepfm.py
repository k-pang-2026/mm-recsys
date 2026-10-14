"""Evaluate frozen offline CTR/CVR classification without serving or B5 dependencies."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import torch

from src.common.artifacts import file_hash, write_json
from src.common.config import load_config
from src.recommendation.datasets import cutoff_for
from src.recommendation.ranking_features import HistoryIndex
from src.recommendation.train_deepfm import (
    load_ranking, measure, prepare, probabilities, tensors,
)


def validate_selection(selection: dict, training: dict, meta: dict) -> None:
    if (selection['selection_split'] != 'valid'
            or selection['model_sha256'] != meta['hashes']['deepfm.pt']
            or selection['config_fingerprint'] != meta['config_fingerprint']
            or selection['best_epoch'] != training['best_epoch']
            or training['bundle']['hashes']['deepfm.pt'] != selection['model_sha256']
            or training['selected_valid'] != selection['selected_valid']):
        raise ValueError('evaluation model differs from frozen valid selection')


def evaluate(cfg: dict, split: str) -> dict:
    torch.set_num_threads(cfg['recommend']['ranking']['threads'])
    output = Path(cfg['paths']['results_dir'])
    selection_path = output / f'ranking_selection_{cfg["scale"]}.json'
    training_path = output / f'ranking_training_{cfg["scale"]}.json'
    selection = json.loads(selection_path.read_text())
    training = json.loads(training_path.read_text())
    data, labels, diagnostics = prepare(cfg, split)
    model, encoder, meta = load_ranking(cfg, data)
    validate_selection(selection, training, meta)
    table = encoder.metadata.item_table(data['products'])
    prior = data['train'] if split == 'valid' else pd.concat(
        [data['train'], data['valid']], ignore_index=True)
    history = HistoryIndex(prior, table, popularity_events=data['train'])
    sparse, dense = encoder.transform(
        labels[split], data['users'], table, history, freeze_at=cutoff_for(data, split))
    values = tensors(labels[split], sparse, dense)
    classification = measure(values, probabilities(
        model, values, cfg['recommend']['ranking']['batch_size']))
    score = classification['ctr']['auc']
    passed = score is not None and score >= cfg['targets']['auc']
    source_paths = [selection_path, training_path] + [Path('src/recommendation') / name for name in (
        'deepfm.py', 'ranking_labels.py', 'ranking_features.py', 'train_deepfm.py', 'eval_deepfm.py')]
    report = dict(
        version='offline-deepfm-classification-v1', scale=cfg['scale'], split=split,
        status='PASS' if passed else 'FAIL', acceptance='UNMEASURED',
        scope='offline classification only; not API, ranked recommendation quality, or B5 acceptance',
        classification=classification, labels=diagnostics[split], ctr_auc_target=cfg['targets']['auc'],
        selection_split='valid', best_epoch=selection['best_epoch'],
        model_sha256=meta['hashes']['deepfm.pt'], feature_fingerprint=meta['feature_fingerprint'],
        ranking_config_fingerprint=meta['config_fingerprint'],
        data_fingerprint=data['manifest']['generation_fingerprint'], data_counts=data['manifest']['counts'],
        history_cutoff=cutoff_for(data, split).isoformat(),
        history_policy='strictly before each exposure, frozen at split origin; popularity fitted on train',
        limitations=['CTR uses linked views as a click proxy; generated exposure/view timestamps coincide',
                     '30min CVR attribution retained; zero positives mean CVR AUC is undefined',
                     'CTR AUC alone does not establish recommendation or conversion quality'],
        sources={str(path): file_hash(path) for path in source_paths},
    )
    path = output / f'ranking_classification_{cfg["scale"]}_{split}.json'
    write_json(path, report)
    print(f'{path}: CTR AUC={score}; CVR={classification["cvr"]["auc_status"]}; {report["status"]}')
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--split', required=True, choices=['valid', 'test'])
    args = parser.parse_args()
    report = evaluate(load_config(), args.split)
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
