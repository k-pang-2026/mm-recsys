"""Read immutable role evidence and assemble an honest submission snapshot."""
from __future__ import annotations

import ast
import json
import math
from pathlib import Path
from typing import Any

from src.common.artifacts import file_hash

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


def collect_quality(root: Path, cfg: dict) -> tuple[dict, dict]:
    """Recompute result rows and raw percentiles; never promote dev evidence."""
    import numpy as np
    from src.evaluation.run_all import metric_rows

    quality = read_json(root, QUALITY)
    valid = read_json(root, 'docs/results/docker/quality_full_valid.json')
    frozen = read_json(root, 'docs/results/docker/quality_selection_full.json')
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
    smoke = read_json(root, SMOKE)
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
        metrics[name] = source(root, QUALITY, value=value, split=row['split'], status='PASS')
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
    metrics['candidate_count'] = source(root, QUALITY, value=count, split='test', status='PASS')
    return metrics, quality


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
