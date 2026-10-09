"""Validate recorded B3a evidence, without reopening frozen test outcomes."""
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = diagnose(json.loads(args.report.read_text()))
    result.update(source=str(args.report), source_sha256=file_hash(args.report))
    write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
