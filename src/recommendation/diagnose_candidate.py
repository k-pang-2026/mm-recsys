"""Diagnose recorded training and B3b valid evidence without tuning on test."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.common.artifacts import file_hash, write_json


def diagnose(report: dict) -> dict:
    checks = {
        'train_only_tiny_fit': report['tiny_train_fit']['status'] == 'PASS',
        'strict_history': report['sampling']['strictly_preceding_history'],
        'random_one_to_four': report['sampling']['random_negatives_per_positive'] == 4,
        'exactly_top300': report['best_valid_exact']['candidate_count_min'] == min(300, report['best_valid_exact']['eligible_catalog']),
        'fixed_origin_valid': report['contract']['split'] == 'valid' and report['contract']['k'] == 300,
        'macro_all_users': report['best_valid_exact']['cohorts']['all']['users'] == report['best_valid_exact']['macro_users'],
        'checkpoint_reload': report['checkpoint_reload'] == 'PASS',
        'gradient_and_updates': all(e['optimizer_updates'] > 0 and e['mean_gradient_norm'] > 0 and e['parameter_update_l2'] > 0 for e in report['epochs']),
        'unit_norm': all(abs(e['mean_user_norm'] - 1) < 1e-5 and abs(e['mean_item_norm'] - 1) < 1e-5 for e in report['epochs']),
        'noncollapsed': all(e['user_dimension_std'] > 1e-4 and e['item_dimension_std'] > 1e-4 for e in report['epochs']),
        'best_valid_checkpoint': report['best_valid_exact']['recall_at_300'] == max(e['valid']['recall_at_300'] for e in report['epochs']),
    }
    recall = report['best_valid_exact']['recall_at_300']
    baselines = {name: score['recall_at_300'] for name, score in report['baselines'].items()}
    return dict(status='PASS' if all(checks.values()) else 'FAIL', stage='B3a', checks=checks,
                scale=report['scale'], contract=report['contract'], valid_exact_recall_at_300=recall,
                baseline_recall=baselines, baseline_lift={name: recall / value - 1 if value else None for name, value in baselines.items()},
                diagnosis='inspect feature/training defects before ANN tuning' if recall < max(baselines.values()) else 'exact encoder exceeds measured baselines',
                full_test_quality='UNMEASURED', ann='UNMEASURED', latency='UNMEASURED')


def diagnose_ann(training: dict, evaluation: dict, benchmark: dict | None = None) -> dict:
    if evaluation['contract']['split'] != 'valid':
        raise ValueError('B3b diagnosis and selection must use valid, not frozen test')
    result = diagnose(training)
    exact = evaluation['exact_flat_ip']
    ann = evaluation['ann_two_tower']
    base = {name: score['recall_at_300'] for name, score in evaluation['baselines'].items()}
    result.update(stage='B3b', valid_ann_recall_at_300=ann['recall_at_300'],
                  ann_agreement_at_300=evaluation['ann_agreement_at_300'],
                  ordered_diagnosis={
                      'a_metric': {'contract': evaluation['contract'], 'eligible_catalog': exact['eligible_catalog'],
                                   'unavailable_truth_retained': exact['unavailable_truth_items'],
                                   'cohorts': ann['cohorts'], 'mapping': evaluation['index_manifest']['mapping']},
                      'b_data_signal': {'baseline_recall': base, 'tiny_train_fit': training['tiny_train_fit'],
                                        'latent_expected_mass': 'UNMEASURED; no irreducible-noise claim'},
                      'c_training': {'best_epoch': training['best_epoch'], 'checkpoint_reload': training['checkpoint_reload'],
                                     'best_epoch_diagnostics': next(e for e in training['epochs'] if e['epoch'] == training['best_epoch']),
                                     'history_baseline_advantage': base['observed_history_profile'] - exact['recall_at_300']},
                      'd_ann': {'exact_recall_at_300': exact['recall_at_300'], 'ann_recall_at_300': ann['recall_at_300'],
                                'agreement_at_300': evaluation['ann_agreement_at_300'],
                                'quality_delta': ann['recall_at_300'] - exact['recall_at_300'],
                                'index_manifest': evaluation['index_manifest']},
                      'e_bounded_valid_experiments': {'runs': [], 'decision': 'retain seeded baseline configuration' if ann['recall_at_300'] >= 0.30 else 'valid improvement required before final test',
                                                     'reason': 'no test-driven selection; do not tune merely to beat a baseline once mandatory threshold passes'}},
                  latency=benchmark or 'UNMEASURED', full_test_quality='UNMEASURED')
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--evaluation', type=Path, help='recorded valid ANN evaluation for B3b diagnosis')
    parser.add_argument('--benchmark', type=Path)
    args = parser.parse_args()
    training = json.loads(args.report.read_text())
    result = (diagnose_ann(training, json.loads(args.evaluation.read_text()),
                          json.loads(args.benchmark.read_text()) if args.benchmark else None)
              if args.evaluation else diagnose(training))
    result.update(source=str(args.report), source_sha256=file_hash(args.report))
    if args.evaluation:
        result['evaluation_source'] = str(args.evaluation)
        result['evaluation_sha256'] = file_hash(args.evaluation)
    if args.benchmark:
        result['benchmark_source'] = str(args.benchmark)
        result['benchmark_sha256'] = file_hash(args.benchmark)
    write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
