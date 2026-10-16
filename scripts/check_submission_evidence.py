"""Read immutable role evidence and assemble an honest submission snapshot."""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from src.common.artifacts import file_hash, fingerprint

QUALITY = 'docs/results/docker/quality_full_test.json'
SMOKE = 'docs/results/docker/smoke_full.json'


def read_json(root: Path, name: str) -> dict:
    """Reject absolute paths, traversal and symlinks escaping the checkout."""
    path = root / name
    if Path(name).is_absolute() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'evidence path escapes checkout: {name}')
    return json.loads(path.read_text(encoding='utf-8'))


def source(root: Path, name: str, **values: Any) -> dict:
    read_json(root, name)
    return dict(source=name, sha256=file_hash(root / name), **values)


def check_hashes(root: Path, hashes: dict) -> None:
    for name, expected in hashes.items():
        path = root / name
        if Path(name).is_absolute() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f'invalid hash path: {name}')
        if not path.is_file() or file_hash(path) != expected:
            raise ValueError(f'evidence changed or missing: {name}')


def read_ab_evidence(root: Path, name: str) -> dict:
    """Restore a large measured A/B report from lossless, hash-checked JSON shards."""
    value = read_json(root, name)
    if value.get('schema') != 'ab-lossless-archive-v1':
        return value
    report = value['report']
    for arm in ('control', 'treatment'):
        statistics: dict = {}
        for shard in value['arm_statistics_shards'][arm]:
            check_hashes(root, {shard['source']: shard['sha256']})
            rows = read_json(root, shard['source'])
            if statistics.keys() & rows.keys():
                raise ValueError('duplicate archived A/B arm statistics')
            statistics.update(rows)
        report['arms'][arm]['arm_statistics'] = statistics
    original = (json.dumps(report, ensure_ascii=False, indent=2, default=str) + '\n').encode()
    if len(original) != value['original_bytes'] or hashlib.sha256(original).hexdigest() != value['original_sha256']:
        raise ValueError('archived A/B report differs from measured original')
    verification = value['verification']
    check_hashes(root, {verification['source']: verification['sha256']})
    verified = read_json(root, verification['source'])
    if (verified['status'] != 'PASS' or verified['scale'] != 'full'
            or verified['sha256'] != value['original_sha256']
            or verified['run_id'] != report['run_id']):
        raise ValueError('archived A/B lacks matching original statistical verification')
    return report


def audit_python(root: Path, paths: list[str], setting_names: list[str]) -> dict:
    """Inventory public signatures, configured seed calls and suspected settings."""
    missing, settings, seeds = [], [], []
    functions = 0
    for name in paths:
        tree = ast.parse((root / name).read_text(encoding='utf-8'), filename=name)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith('_'):
                functions += 1
                args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
                args += [arg for arg in (node.args.vararg, node.args.kwarg) if arg is not None]
                absent = [arg.arg for arg in args if arg.arg not in ('self', 'cls') and arg.annotation is None]
                if node.returns is None:
                    absent.append('return')
                if absent:
                    missing.append(dict(file=name, line=node.lineno, function=node.name, missing=absent))
            if isinstance(node, ast.Call):
                fn = node.func
                called = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else ''
                if called in ('set_seed', 'manual_seed', 'seed'):
                    seeds.append(dict(file=name, line=node.lineno, call=ast.unparse(node)))
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.lower() in setting_names:
                        settings.append(dict(file=name, line=node.lineno, name=target.id, value=node.value.value))
            if isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if keyword.arg in setting_names and isinstance(keyword.value, ast.Constant):
                        settings.append(dict(file=name, line=node.lineno, name=keyword.arg, value=keyword.value.value))
    return dict(files=len(paths), public_functions=functions, missing_annotations=missing,
                seed_calls=seeds, suspected_settings=settings,
                scope='AST inventory; absence of findings does not prove complete typing or determinism')


def collect_quality(root: Path, cfg: dict, evidence_dir: str = "docs/results/docker") -> tuple[dict, dict]:
    """Recompute result rows and raw percentiles; never promote dev evidence."""
    import numpy as np
    from src.evaluation.run_all import metric_rows

    quality_path = evidence_dir + "/quality_full_test.json"
    smoke_path = evidence_dir + "/smoke_full.json"
    quality = read_json(root, quality_path)
    if evidence_dir != 'docs/results/docker':
        validate_configuration(root, cfg, quality, evidence_dir)
    valid = read_json(root, evidence_dir + '/quality_full_valid.json')
    frozen = read_json(root, evidence_dir + '/quality_selection_full.json')
    check_hashes(root, {frozen['source']: frozen['sha256'], **quality['identity']['source_hashes'],
                       **quality['identity']['docker_sources']})
    if (quality['scale'] != 'full' or quality['split'] != 'test'
            or quality['status'] != 'PASS' or quality['quality_status'] != 'PASS'
            or quality['test_used_for_selection'] is not False
            or frozen['selected_on'] != 'valid'
            or valid['identity'] != quality['identity'] or frozen['identity'] != quality['identity']
            or read_json(root, frozen['source']) != valid):
        raise ValueError('full frozen valid/test evidence is inconsistent')
    counts = quality['data_counts']
    if any(counts[key] < minimum for key, minimum in [('products', 50000), ('users', 10000), ('events', 1000000)]):
        raise ValueError('full dataset counts are insufficient')
    check_hashes(root, {quality['latency_source']['source']: quality['latency_source']['sha256']})
    smoke = read_json(root, smoke_path)
    if smoke['scale'] != 'full' or smoke['data_fingerprint'] != quality['data_fingerprint'] or smoke['status'] != 'PASS':
        raise ValueError('smoke and full test datasets differ')
    if any(quality[key] != smoke['benchmark'][other] for key, other in
           [('candidate_latency', 'candidate'), ('feature_store', 'feature')]):
        raise ValueError('latency evidence differs from raw smoke')
    if quality['api']['modes'] != smoke['benchmark']['modes']:
        raise ValueError('HTTP latency differs from raw smoke')
    for row in quality['api']['modes'].values():
        samples = row['http_samples_ms']
        if (row['warmup'] < 10 or row['requests'] < 100 or len(samples) != row['requests']
                or row['errors'] != 0 or not np.isfinite(samples).all() or min(samples) < 0
                or float(np.percentile(samples, 95)) != row['http']['p95_ms']):
            raise ValueError('invalid HTTP benchmark samples')
    for key, sample_key, calls_key, p95_key in [('candidate_latency', 'elapsed_ms', 'calls', 'p95_ms'),
                                              ('feature_store', 'samples_ms', 'requests', 'latency_ms')]:
        row = quality[key]
        p95 = row[p95_key]['p95'] if key == 'feature_store' else row[p95_key]
        if (row['warmup'] < 10 or row[calls_key] < 100 or len(row[sample_key]) != row[calls_key]
                or not np.isfinite(row[sample_key]).all() or min(row[sample_key]) < 0
                or float(np.percentile(row[sample_key], 95)) != p95):
            raise ValueError(f'invalid raw samples: {key}')
    expected = metric_rows(cfg, 'test', quality['search'], quality['recommendation'], quality['api'],
                           quality['candidate_latency'], quality['feature_store'])
    if expected != quality['metrics']:
        raise ValueError('metric rows differ from original measured fields/targets')
    rows = {row['name']: row for row in expected}
    if set(rows) != set(cfg['targets']) or len(rows) != len(expected):
        raise ValueError('missing or duplicate target metric')
    metrics = {}
    for name, target in cfg['targets'].items():
        row = rows[name]
        value = row['value']
        if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                or row['status'] != 'PASS' or (value > target if name.endswith('_ms') else value < target)):
            raise ValueError(f'invalid or failed metric: {name}')
        metrics[name] = source(root, quality_path, value=value, split=row['split'], status='PASS')
    count = quality['recommendation']['candidate']['ann_two_tower']['candidate_count_min']
    if count < cfg['recommend']['candidate_k'] or quality['recommendation']['feasible_constraint_violations']:
        raise ValueError('candidate count or feasible constraint failure')
    rec = quality['recommendation']
    cohort = rec['cohort']['total_users']
    if cohort != min(cfg['recommend']['evaluation']['coverage_users'], counts['users']):
        raise ValueError('coverage user cohort changed')
    for row in rec['metrics'].values():
        if row['coverage_users'] != cohort or row['catalog_items'] != counts['products'] or row['coverage'] != row['unique_recommended_items'] / counts['products']:
            raise ValueError('coverage denominator changed')
    metrics['candidate_count'] = source(root, quality_path, value=count, split='test', status='PASS')
    return metrics, quality


def validate_configuration(root: Path, cfg: dict, quality: dict, evidence_dir: str) -> None:
    """Artifact aliases may change locations/endpoints, never the measured recipe."""
    from src.simulator.generate import generation_identity
    measured = read_json(root, evidence_dir + '/configuration_full.json')
    if fingerprint(measured) != quality['identity']['config_fingerprint']:
        raise ValueError('measured configuration snapshot differs from frozen quality')
    actual, expected = copy.deepcopy(measured), copy.deepcopy(cfg)
    for value in (actual, expected):
        value.pop('paths', None)
        value['redis'].pop('host', None)
        value['redis'].pop('port', None)
    if actual != expected:
        raise ValueError('native validation recipe differs from measured configuration')
    if fingerprint(generation_identity(cfg)) != quality['data_fingerprint']:
        raise ValueError('native generation recipe/order differs from measured dataset')


def assemble_acceptance(root: Path, cfg: dict, submission_path: str) -> dict:
    """B11 aggregates evidence; only INTEGRATE may establish a full system PASS."""
    metrics, quality = collect_quality(root, cfg)
    smoke = read_json(root, SMOKE)
    checks = {}
    for name in ('api_schemas', 'session_response'):
        ok = smoke['checks'].get(name) == 'PASS'
        checks[name] = source(root, SMOKE, status='PASS' if ok else 'FAIL', exit_code=0 if ok else 1,
                             scope='historical B10 full HTTP execution, not a new B11 full run')
    checks['docker_reproduction'] = source(root, 'docs/results/docker/verified_full.json',
        status='UNMEASURED', exit_code=None,
        reason='B10 full Compose passed with existing data/search/HF cache; fresh-clone complete regeneration unmeasured')
    checks['ab_statistics'] = source(root, 'docs/results/ab_test.json', status='UNMEASURED', exit_code=None,
        reason='C dev 200 users/arm, 30-day in-memory simulation; no matching full/live Redis experiment')
    checks['ct_retrain_and_rollback'] = source(root, 'docs/results/ct_dev_fixture.json', status='UNMEASURED', exit_code=None,
        reason='C controlled fixture passed retraining/promotion/rollback; B10 full only reloaded the same v1.0')
    submission = read_json(root, submission_path)
    ready = submission['readiness_status'] == 'PASS'
    checks['submission'] = source(root, submission_path, status='PASS' if ready else 'BLOCKED',
                                  exit_code=0 if ready else None, reason=submission['blockers'])
    return dict(scale='full', status='UNMEASURED', stage='B11', data_fingerprint=quality['data_fingerprint'],
                data_counts=quality['data_counts'], metrics=metrics, checks=checks,
                limitations=quality['limitations'] + [
                    'P0 real-dataset interpretation awaits instructor decision',
                    'source/hash audit reuses B10 measurements; it is not a new model quality run',
                    'INTEGRATE must recheck every mandatory check before final acceptance PASS'])


def assemble_integration(root: Path, cfg: dict, submission_path: str, evidence_dir: str,
                         checks_path: str) -> dict:
    """Aggregate executed integration checks; no dev/fixture result is promoted by scale."""
    metrics, quality = collect_quality(root, cfg, evidence_dir)
    execution = read_json(root, checks_path)
    checks = collect_integration_checks(root, execution, quality['data_fingerprint'])
    report = read_json(root, submission_path)
    ready = report['delivery_status'] == report['readiness_status'] == 'PASS'
    checks['submission'] = source(root, submission_path, status='PASS' if ready else 'BLOCKED',
                                  exit_code=0 if ready else None)
    passed = ready and all(entry.get('status') == 'PASS' and entry.get('exit_code') == 0 for entry in checks.values())
    return dict(scale='full', stage='INTEGRATE', status='PASS' if passed else 'UNMEASURED',
                data_fingerprint=quality['data_fingerprint'], data_counts=quality['data_counts'],
                metrics=metrics, checks=checks, limitations=execution.get('limitations', []),
                dataset_scope=read_json(root, 'docs/submission/dataset_scope.json'))


def collect_integration_checks(root: Path, execution: dict, data_fingerprint: str) -> dict:
    """A receipt cannot promote a reused clone, dev simulation or retained CT to full PASS."""
    if execution['data_fingerprint'] != data_fingerprint:
        raise ValueError('integration check dataset differs from frozen quality')
    required = {'docker_reproduction', 'api_schemas', 'ab_statistics', 'session_response', 'ct_retrain_and_rollback'}
    if set(execution['checks']) != required:
        raise ValueError('integration required checks are missing')
    checks = {name: dict(entry) for name, entry in execution['checks'].items()}
    for name, entry in checks.items():
        check_hashes(root, {entry['source']: entry['sha256']})
        if entry['status'] != 'PASS':
            continue
        measured = read_json(root, entry['source'])
        if (entry['exit_code'] != 0 or measured.get('status') != 'PASS'
                or measured.get('scale') != 'full' or measured.get('data_fingerprint') != data_fingerprint):
            raise ValueError(f'not matching full executed evidence: {name}')
        if name == 'docker_reproduction':
            if (measured.get('initial_data_files') != 0 or measured.get('initial_model_files') != 0
                    or not measured.get('prepared_data_and_models_from_empty')):
                raise ValueError('fresh-clone reproduction reused prepared artifacts')
            prep = measured['preparation']
            check_hashes(root, {prep['source']: prep['sha256']})
            prepared = read_json(root, prep['source'])
            if (prepared['status'] != 'PASS' or prepared['scale'] != 'full'
                    or prepared['data_fingerprint'] != data_fingerprint
                    or any(prepared['artifact_state_before'].values())):
                raise ValueError('fresh preparation identity/state differs')
            runtime = measured['runtime_sources']
            check_hashes(root, {runtime['source']: runtime['sha256']})
            deployed = read_json(root, runtime['source'])
            if deployed['status'] != 'PASS':
                raise ValueError('deployed runtime sources were not verified')
            check_hashes(root, deployed['source_hashes'])
        elif name == 'ab_statistics':
            original = measured['source']
            check_hashes(root, {original: measured['sha256']})
            experiment = read_ab_evidence(root, original)
            if (experiment['scale'] != 'full' or experiment['status'] != 'PASS'
                    or experiment['identity']['data_fingerprint'] != data_fingerprint
                    or experiment['days'] != 30 or experiment['top_n'] != 10
                    or any(experiment['arms'][arm]['users'] != 5000 for arm in ('control', 'treatment'))):
                raise ValueError('full A/B population or execution differs')
            check_hashes(root, experiment['identity']['source_hashes'])
        elif name == 'ct_retrain_and_rollback':
            if measured.get('schema') == 'ct-full-separated-lifecycle-v1':
                validate_separated_ct(root, measured, data_fingerprint)
                continue
            if (not measured.get('real_reload_and_rollback') or not all(measured['checks'].values())
                    or measured['retraining']['status'] != 'PROMOTED'
                    or measured['retraining']['comparison']['split'] != 'valid'
                    or measured['observed_new_events'] < 10000 or measured['threshold'] != 10000):
                raise ValueError('full CT retraining/promotion/rollback was not executed')
            check_hashes(root, measured['source_hashes'])
        else:
            expected = ('api_schemas',) if name == 'api_schemas' else ('session_response', 'live_redis_mab', 'max_reward', 'dedup_feedback')
            if any(measured['checks'].get(key) != 'PASS' for key in expected):
                raise ValueError(f'HTTP/Redis execution incomplete: {name}')
            if name == 'session_response':
                check_hashes(root, measured['source_hashes'])
    return checks


def validate_separated_ct(root: Path, receipt: dict, data_fingerprint: str) -> None:
    """Keep natural retention separate from a measured full-size initial-fault rollback drill."""
    values = {}
    for key in ('natural', 'controlled_lifecycle', 'training', 'candidate_validation', 'configuration'):
        link = receipt[key]
        check_hashes(root, {link['source']: link['sha256']})
        values[key] = read_json(root, link['source'])
    natural, drill = values['natural'], values['controlled_lifecycle']
    if (natural['status'] != 'PARTIAL' or natural['scale'] != 'full'
            or natural['data_fingerprint'] != data_fingerprint
            or natural['retraining']['status'] != 'RETAINED'
            or natural['real_reload_and_rollback']
            or natural['observed_new_events'] < 10000 or natural['threshold'] != 10000
            or natural['repeated_trigger']['status'] != 'WAITING'
            or not all(natural['checks'].get(key) is True for key in
                       ('full_three_model_retraining', 'threshold', 'event_watermark', 'paired_valid'))):
        raise ValueError('natural full CT retention/training evidence is incomplete')
    check_hashes(root, natural['source_hashes'])
    counts = drill['counts']
    if (drill['status'] != 'PASS' or drill['scale'] != 'full'
            or drill['scenario'] != 'controlled_initial_constant_ranker'
            or drill['natural_retraining'] != 'RETAINED'
            or drill['data_fingerprint'] != data_fingerprint
            or any(counts[key] < minimum for key, minimum in [('products', 50000), ('users', 10000), ('events', 1000000)])
            or not drill['production_unchanged'] or not drill['real_reload_and_rollback']
            or drill['fixture_active'] != 'v1.0' or drill['natural'] != receipt['natural']):
        raise ValueError('separate full controlled CT lifecycle evidence is incomplete')
    check_hashes(root, drill['source_hashes'])
    from src.ct.retrain_trigger import settings
    expected_guard = settings(values['configuration'])
    if drill['guard'] != expected_guard:
        raise ValueError('controlled CT changed the original promotion guard')
    comparison = drill['comparison']
    before, after = comparison['baseline'], comparison['candidate']
    actual = natural['retraining']['comparison']['candidate']
    if (comparison['split'] != 'valid' or not comparison['validation_fingerprint']
            or before['validation_fingerprint'] != comparison['validation_fingerprint']
            or after['validation_fingerprint'] != comparison['validation_fingerprint']
            or before['ctr_auc'] != .5
            or not after['ctr_auc'] > before['ctr_auc'] + expected_guard['min_improvement']
            or after['ctr_auc'] < expected_guard['promotion_floor']
            or abs(after['ctr_auc'] - actual['ctr_auc']) > 1e-12
            or after['ctr_samples'] != actual['ctr_samples'] or after['ctr_samples'] <= 0
            or drill['candidate_hashes'] != drill['original_candidate_hashes']
            or drill['candidate_hashes'] != values['candidate_validation']['bundle_hashes']):
        raise ValueError('controlled paired valid comparison or candidate identity differs')
    traffic = drill['http']
    if (len(traffic) != 6 or any(row['status'] != 200 for row in traffic)
            or [row['version'] for row in traffic] != ['v1.0', 'v1.0', 'v1.1', 'v1.1', 'v1.0', 'v1.0']
            or len(drill['reloads']) != 2):
        raise ValueError('full controlled HTTP reload/rollback traffic missing')
    lifecycle = drill['lifecycle']
    check_hashes(root, {lifecycle['source']: lifecycle['sha256']})
    events = [json.loads(line)['event'] for line in (root / lifecycle['source']).read_text().splitlines()]
    if receipt.get('controlled_reload'):
        reload_log = receipt['controlled_reload']
        check_hashes(root, {reload_log['source']: reload_log['sha256']})
        # The HTTP app's components() logger and the drill registry may use
        # distinct log paths. Preserve both original streams, without inventing events.
        events += [json.loads(line)['event'] for line in (root / reload_log['source']).read_text().splitlines()]
    if not {'registered', 'initialized', 'promoted', 'rollback', 'reloaded'} <= set(events) or events.count('reloaded') != 2:
        raise ValueError('controlled actual registry/reload lifecycle missing')
    training = values['training']
    if training['status'] != 'PASS' or set(training['training_sources']) != {'candidate', 'ranking', 'session'}:
        raise ValueError('actual full three-model training reports missing')
    for name, link in training['training_sources'].items():
        check_hashes(root, {link['source']: link['sha256']})
        trained = read_json(root, link['source'])
        if (link['sha256'] != natural['retraining']['comparison']['training_reports'][name]
                or trained['status'] != 'PASS' or trained['scale'] != 'full'
                or trained['checkpoint_reload'] != 'PASS'):
            raise ValueError('full training report identity/reload differs')
