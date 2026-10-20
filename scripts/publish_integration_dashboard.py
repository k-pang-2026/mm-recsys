"""Publish a validated INTEGRATE result without rewriting frozen quality evidence."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_submission_evidence import (assemble_integration, check_hashes,
                                               read_ab_evidence, read_json, source)
from src.common.artifacts import write_json
from src.common.config import load_config
from src.ct.model_registry import ModelRegistry
from src.evaluation.acceptance import validate_acceptance


def publish(root: Path, submission: str, output: Path) -> dict:
    """Require matching frozen quality, executed checks, submission and source hashes."""
    if not output.resolve().is_relative_to(root.resolve()):
        raise ValueError('dashboard output must stay within the checkout')
    if output.name != 'evaluation_full_test.json':
        raise ValueError('publish to a dashboard evaluation_full_test.json, preserving frozen quality files')
    cfg = load_config()
    receipt = read_json(root, submission)
    check_hashes(root, receipt['input_hashes'])
    for entry in receipt['commands'].values():
        check_hashes(root, {entry['source']: entry['sha256']})
    expected = assemble_integration(root, cfg, submission, receipt['evidence_dir'], receipt['integration_checks'])
    acceptance = read_json(root, 'docs/results/final_acceptance.json')
    if acceptance != expected:
        raise ValueError('final acceptance differs from the executed integration evidence')
    manifest = json.loads((Path(cfg['paths']['data_dir']) / 'split_manifest.json').read_text())
    validate_acceptance(acceptance, cfg, manifest, root)
    quality_name = receipt['evidence_dir'] + '/quality_full_test.json'
    report = copy.deepcopy(read_json(root, quality_name))
    manifest_path = Path(cfg['paths']['data_dir']) / 'split_manifest.json'
    manifest_path = manifest_path if manifest_path.is_absolute() else root / manifest_path
    check_hashes(root, {str(manifest_path.relative_to(root)): report['identity']['data_manifest_sha256'],
                        **report['identity']['models']})
    check_hashes(root, {str((manifest_path.parent / name).relative_to(root)): digest
                        for name, digest in manifest.get('file_hashes', {}).items()})
    for name in report['identity']['models']:
        metadata = read_json(root, name)
        check_hashes(root, {str((Path(name).parent / child)): digest
                            for child, digest in metadata.get('hashes', {}).items()})
    registry = Path(cfg['paths']['model_dir']) / 'registry.json'
    registry = registry if registry.is_absolute() else root / registry
    versions = ModelRegistry(registry.parent, root / cfg['paths']['results_dir'] / 'ct_log.jsonl')
    if versions.read()['active'] != 'v1.0':
        raise ValueError('frozen initial quality cannot describe a different active release')
    versions.verify('v1.0')
    ab_check = acceptance['checks']['ab_statistics']
    ab_link = read_json(root, ab_check['source'])
    experiment = read_ab_evidence(root, ab_link['source'])
    ct = read_json(root, acceptance['checks']['ct_retrain_and_rollback']['source'])
    natural = read_json(root, ct['natural']['source']) if ct.get('schema') == 'ct-full-separated-lifecycle-v1' else ct
    if experiment['identity']['data_fingerprint'] != report['data_fingerprint']:
        raise ValueError('dashboard A/B and quality datasets differ')
    for kind in ('candidate', 'ranking', 'session'):
        if (experiment['identity']['bundle_metadata'][kind]['hashes']
                != report['recommendation']['models'][kind]['hashes']):
            raise ValueError('dashboard A/B and quality models differ')
    report['acceptance'] = acceptance['status']
    report['model_version'] = 'v1.0'
    report['ab'] = dict(status='MEASURED', days=experiment['days'], run_id=experiment['run_id'],
        arms={arm: {key: value for key, value in values.items() if key != 'arm_statistics'}
              for arm, values in experiment['arms'].items()},
        inference=experiment['inference'], limitations=experiment['limitations'])
    report['integration'] = dict(stage='INTEGRATE', status=acceptance['status'],
        final_acceptance=source(root, 'docs/results/final_acceptance.json'),
        frozen_quality=source(root, quality_name), checks=acceptance['checks'],
        ct=dict(retraining=natural['retraining']['status'], observed_new_events=natural['observed_new_events'],
                lifecycle=acceptance['checks']['ct_retrain_and_rollback']['status'], scope=ct.get('scope')),
        limitations=acceptance['limitations'])
    write_json(output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--submission', required=True, help='validated submission checks.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = publish(ROOT, args.submission, args.output)
    print(f"대시보드 최종 통합 판정: {report['acceptance']}; {args.output}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
