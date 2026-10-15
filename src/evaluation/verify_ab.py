"""Check A/B counts, cluster statistics, input hashes and an actual seeded rerun."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.common.artifacts import file_hash, fingerprint, write_json
from src.common.config import load_config
from src.evaluation.ab_statistics import binary_comparison, clustered_rate


def verify(path: Path, cfg: dict, repeat: Path | None = None) -> dict:
    report = json.loads(path.read_text())
    identity = report['identity']
    manifest = json.loads((Path(cfg['paths']['data_dir']) / 'split_manifest.json').read_text())
    if report['status'] != 'PASS' or identity['config_fingerprint'] != fingerprint(cfg):
        raise ValueError('A/B status/config mismatch')
    if identity['data_fingerprint'] != manifest['generation_fingerprint'] or identity['data_hashes'] != manifest['file_hashes']:
        raise ValueError('A/B dataset mismatch')
    for name, digest in identity['source_hashes'].items():
        if file_hash(Path(name)) != digest:
            raise ValueError(f'A/B source changed: {name}')
    assigned = report['assignment']
    if (set(assigned['control']) & set(assigned['treatment'])
            or len(assigned['control']) != len(assigned['treatment'])
            or report['assignment_sha256'] != fingerprint(assigned)):
        raise ValueError('invalid randomization')
    for arm in ('control', 'treatment'):
        rows, summary = report['user_outcomes'][arm], report['arms'][arm]
        if [r['user_id'] for r in rows] != assigned[arm] or len(set(assigned[arm])) != len(rows):
            raise ValueError('user assignment/outcome mismatch')
        if summary['users'] != len(rows) or len(rows) < 2:
            raise ValueError('invalid experimental population')
        for row in rows:
            if not 0 <= row['purchases'] <= row['clicks'] <= row['impressions'] <= report['days'] * report['top_n']:
                raise ValueError('noncausal outcome counts')
            if not 0 <= row['explorations'] <= row['impressions']:
                raise ValueError('invalid exploration counts')
        for key in ('impressions', 'clicks', 'purchases', 'explorations'):
            if sum(r[key] for r in rows) != summary[key]:
                raise ValueError('aggregate outcome mismatch')
        for metric, numerator, denominator in [('ctr', 'clicks', 'impressions'),
                ('cvr', 'purchases', 'impressions'), ('purchase_given_click', 'purchases', 'clicks'),
                ('exploration_rate', 'explorations', 'impressions')]:
            expected = summary[numerator] / summary[denominator] if summary[denominator] else None
            if summary[metric] != expected:
                raise ValueError(f'invalid {metric} denominator')
        if sum(v['exposures'] for v in summary['arm_statistics'].values()) != summary['impressions']:
            raise ValueError('MAB exposures differ from observed impressions')
        if summary['unattributed_feedback'] != 0:
            raise ValueError('unattributed feedback')
        if summary['users_clicked'] != sum(r['clicks'] > 0 for r in rows) or summary['users_purchased'] != sum(r['purchases'] > 0 for r in rows):
            raise ValueError('independent user counts differ')
    a, b = report['arms']['control'], report['arms']['treatment']
    for name, key in [('any_click', 'users_clicked'), ('any_purchase', 'users_purchased')]:
        if report['inference']['independent_user_risks'][name] != binary_comparison(a[key], a['users'], b[key], b['users']):
            raise ValueError('user-risk inference mismatch')
    for metric, numerator in [('ctr', 'clicks'), ('cvr', 'purchases')]:
        if report['inference'][metric] != clustered_rate(report['user_outcomes']['control'], report['user_outcomes']['treatment'], numerator, 'impressions'):
            raise ValueError('cluster inference mismatch')
    equality = 'UNMEASURED'
    if repeat is not None:
        if json.loads(repeat.read_text()) != report:
            raise ValueError('seeded rerun differs from original report')
        equality = 'PASS'
    result = dict(status='PASS', scale=report['scale'], acceptance='UNMEASURED',
        source=str(path), sha256=file_hash(path), run_id=report['run_id'],
        data_fingerprint=identity['data_fingerprint'], checks='assignment, causal counts, denominators, MAB exposure/feedback accounting, independent-user tests, cluster confidence intervals, config/data/source hashes',
        seeded_rerun=equality, repeat_sha256=file_hash(repeat) if repeat else None)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--repeat', type=Path)
    args = parser.parse_args()
    cfg = load_config()
    root = Path(cfg['paths']['results_dir'])
    result = verify(args.report or root / 'ab_test.json', cfg, args.repeat)
    output = root / 'experiments' / 'C' / f'ab_verification_{cfg["scale"]}.json'
    write_json(output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
