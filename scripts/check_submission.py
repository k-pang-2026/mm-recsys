#!/usr/bin/env python3
"""Validate B11 deliverables and separately report final submission readiness."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.common.artifacts import file_hash, write_json
from src.common.config import load_config
from scripts.check_submission_evidence import (assemble_acceptance, audit_python, check_hashes,
                                                collect_quality, read_json)

OUTPUT = 'docs/results/final_submission'


def full_config() -> dict:
    previous = os.environ.get('SCALE')
    try:
        os.environ['SCALE'] = 'full'
        return load_config()
    finally:
        if previous is None:
            os.environ.pop('SCALE', None)
        else:
            os.environ['SCALE'] = previous


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(['git', *args], cwd=root, text=True, timeout=30).strip()


def run_check(root: Path, name: str, command: list[str], env: dict | None = None) -> dict:
    path = root / OUTPUT / f'{name}.txt'
    started = time.perf_counter()
    try:
        with path.open('w', encoding='utf-8') as output:
            result = subprocess.run(command, cwd=root, stdout=output, stderr=subprocess.STDOUT,
                                    env=env, timeout=1800)
        code = result.returncode
    except subprocess.TimeoutExpired:
        code = 124
    return dict(status='PASS' if code == 0 else 'FAIL', exit_code=code, command=command,
                source=str(path.relative_to(root)), sha256=file_hash(path),
                elapsed_seconds=time.perf_counter() - started)


def files_check(root: Path, policy: dict) -> dict:
    required = policy['required_files'] + policy['modules']
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        raise ValueError(f'missing submission files/modules: {missing}')
    for name in policy['modules']:
        compile((root / name).read_text(encoding='utf-8'), name, 'exec')
    tracked = git(root, 'ls-files', '-z').split('\0')
    forbidden = [name for name in tracked if name and (
        name.startswith(('data/', 'models/')) and not name.endswith('/.gitkeep')
        or name.startswith(('.venv/', '.cache/')) or name == '.env.local' or name.endswith('.pdf'))]
    if '.env' not in tracked or forbidden:
        raise ValueError(f'tracked defaults missing or forbidden bulk/private files: {forbidden}')
    for name in ('.env.local', '.venv/probe', 'data/probe.parquet', 'models/probe.pt'):
        result = subprocess.run(['git', 'check-ignore', '-q', name], cwd=root)
        if result.returncode != 0:
            raise ValueError(f'private/generated files are not ignored: {name}')
    # Read only committed non-secret defaults. Never inspect .env.local.
    if re.search(r'(?im)^[A-Z_]*(TOKEN|PASSWORD|SECRET|API_KEY)[A-Z_]*\s*=\s*\S+', (root / '.env').read_text()):
        raise ValueError('suspected secret in tracked .env (value withheld)')
    p0 = (root / 'docs/data_sources.md').read_text()
    if 'UNRESOLVED' not in p0 or '강사' not in p0:
        raise ValueError('P0 unresolved dataset interpretation must be explicit')
    matrix = read_json(root, 'docs/submission/requirements.json')
    for entry in matrix['entries']:
        for name in entry['files'] + entry['tests']:
            if not (root / name).is_file():
                raise ValueError(f'requirement mapping references missing file: {name}')
        check_hashes(root, {entry['source']: entry['sha256']})
    return dict(status='PASS', required_count=len(required), bulk_and_private_tracked=forbidden,
                hashes={name: file_hash(root / name) for name in required})


def live_check(url: str) -> dict:
    import httpx
    from src.common.schemas import RecommendResponse, SearchResponse
    try:
        with httpx.Client(base_url=url, timeout=60, trust_env=False) as client:
            ready = client.get('/ready')
            if ready.status_code != 200 or ready.json().get('status') != 'ready':
                return dict(status='BLOCKED', reason='API models are not ready', http_status=ready.status_code, url=url)
            search = client.post('/api/search', json=dict(query_text='black shirt', top_k=10))
            search.raise_for_status()
            parsed = SearchResponse.model_validate(search.json())
            if parsed.search_type != 'text' or len(parsed.results) != 10:
                raise ValueError('text search returned unexpected mode/count')
            recommendations = {}
            for user in ('U000001', 'submission-unknown-user'):
                response = client.get('/api/recommend', params=dict(user_id=user, top_n=10))
                response.raise_for_status()
                parsed_rec = RecommendResponse.model_validate(response.json())
                if parsed_rec.user_id != user or len(parsed_rec.recommendations) != 10:
                    raise ValueError('known/unknown recommendation schema/count mismatch')
                recommendations[user] = len(parsed_rec.recommendations)
            invalid = client.post('/api/search', json={})
            if invalid.status_code != 422:
                raise ValueError('empty search must return 422')
            return dict(status='PASS', url=url, readiness=ready.json(), search_results=len(parsed.results),
                        recommendation_counts=recommendations, invalid_search_status=invalid.status_code,
                        scope='new B11 live text and known/unknown recommendation schema checks; no quality/latency measurement')
    except httpx.TransportError as error:
        return dict(status='BLOCKED', url=url, reason=f'API unavailable: {type(error).__name__}')
    except (ValueError, httpx.HTTPStatusError) as error:
        return dict(status='FAIL', url=url, reason=str(error))


def check_repository_evidence(root: Path) -> dict:
    report = read_json(root, f'{OUTPUT}/repository.json')
    if report.get('status') != 'PASS' or report.get('access', {}).get('status') != 'PASS':
        return dict(status='BLOCKED', reason='repository/access verification unavailable')
    for role, info in read_json(root, 'docs/submission/contributions.json')['roles'].items():
        if not info['name'] or not info['prs']:
            raise ValueError(f'missing contribution evidence: {role}')
        for pr in info['prs']:
            remote = report['pull_requests'][str(pr['number'])]
            if not remote['merged'] or remote['base'] != 'main' or pr['head_sha'] != remote['head_sha']:
                raise ValueError(f'contribution PR not verified: {role}/{pr["number"]}')
            if 'merged_commit_sha' in pr:
                merge = pr['merged_commit_sha']
                parents = git(root, 'show', '-s', '--format=%P', merge).split()
                subject = git(root, 'show', '-s', '--format=%s', merge)
                if (len(parents) != 2 or parents[1] != pr.get('merged_head_sha')
                        or f'Merge pull request #{pr["number"]} ' not in subject
                        or not pr.get('verification_note')):
                    raise ValueError('disclosed historical PR merge is inconsistent')
                retained = merge
            else:
                retained = pr['head_sha']
            subprocess.run(['git', 'merge-base', '--is-ancestor', retained, 'origin/main'], cwd=root, check=True)
    return dict(status='PASS', access=report['access'], checked_at=report['checked_at'],
                source=f'{OUTPUT}/repository.json', sha256=file_hash(root / OUTPUT / 'repository.json'),
                scope='read-only remote snapshot; stage B11 push/PR still awaits explicit approval')


def verify_saved(root: Path) -> dict:
    report = read_json(root, f'{OUTPUT}/checks.json')
    check_hashes(root, report['input_hashes'])
    for entry in report['commands'].values():
        check_hashes(root, {entry['source']: entry['sha256']})
    if report['delivery_status'] != 'PASS':
        raise ValueError('saved B11 delivery did not pass')
    cfg = full_config()
    collect_quality(root, cfg)
    expected = assemble_acceptance(root, cfg, f'{OUTPUT}/checks.json')
    if read_json(root, 'docs/results/final_acceptance.json') != expected:
        raise ValueError('final acceptance differs from measured inputs/submission readiness')
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-url', default='http://127.0.0.1:8000')
    parser.add_argument('--verify-existing', action='store_true')
    parser.add_argument('--require-ready', action='store_true', help='exit 2 unless all final submission conditions pass')
    args = parser.parse_args()
    if args.verify_existing:
        report = verify_saved(ROOT)
    else:
        (ROOT / OUTPUT).mkdir(parents=True, exist_ok=True)
        policy = read_json(ROOT, 'docs/submission/check_policy.json')
        files = files_check(ROOT, policy)
        paths = sorted(str(p.relative_to(ROOT)) for base in ('src', 'dashboard', 'docker')
                       for p in (ROOT / base).rglob('*.py'))
        paths += ['scripts/check_submission.py', 'scripts/check_submission_evidence.py']
        audit = audit_python(ROOT, paths, policy['setting_names'])
        write_json(ROOT / OUTPUT / 'python_audit.json', audit)
        commands = {}
        commands['mypy_submission'] = run_check(ROOT, 'mypy_submission', [sys.executable, '-m', 'mypy',
            '--explicit-package-bases', '--follow-imports=silent', 'scripts/check_submission.py', 'scripts/check_submission_evidence.py'])
        commands['mypy_repository'] = run_check(ROOT, 'mypy_repository', [sys.executable, '-m', 'mypy',
            '--ignore-missing-imports', 'src', 'dashboard', 'docker'])
        commands['pip_check'] = run_check(ROOT, 'pip_check', [sys.executable, '-m', 'pip', 'check'])
        env = {**os.environ, 'PYTHONHASHSEED': str(load_config()['seed']),
               'REDIS_HOST': '127.0.0.1', 'RUN_REDIS_TESTS': '1'}
        commands['pytest'] = run_check(ROOT, 'pytest', [sys.executable, '-m', 'pytest',
            '-p', 'src.serving.pytest_support', '-q', 'tests',
            '--junitxml=' + OUTPUT + '/pytest.xml'], env)
        live = live_check(args.api_url)
        repository = check_repository_evidence(ROOT)
        cfg = full_config()
        _, quality = collect_quality(ROOT, cfg)
        blockers = list(policy['pending_integration'])
        if commands['mypy_repository']['status'] != 'PASS':
            blockers.append('repository-wide mypy has existing errors; see the complete log, repair in INTEGRATE/owning role')
        if audit['missing_annotations']:
            blockers.append('public signature annotations incomplete; see python_audit.json')
        if live['status'] != 'PASS':
            blockers.append('live API schemas: ' + live['status'])
        if repository['status'] != 'PASS':
            blockers.append('evaluator access: BLOCKED')
        delivery = all(commands[k]['status'] == 'PASS' for k in ('mypy_submission', 'pip_check', 'pytest'))
        delivery = delivery and live['status'] != 'FAIL'
        input_names = set(files['hashes']) | set(paths) | {'docs/submission/check_policy.json',
            'docs/submission/contributions.json', 'docs/submission/requirements.json',
            'docs/submission/config_snapshot.json', 'config.yaml', 'config/search.yaml', 'config/recommend.yaml',
            'config/serving.yaml', 'docs/results/gates/B9.json', 'docs/results/gates/B10.json',
            QUALITY_PATH, 'docs/results/docker/quality_full_valid.json', 'docs/results/docker/quality_selection_full.json',
            'docs/results/docker/smoke_full.json', 'docs/results/docker/verified_full.json',
            'docs/results/ab_test.json', 'docs/results/ct_dev_fixture.json', f'{OUTPUT}/repository.json',
            f'{OUTPUT}/python_audit.json', f'{OUTPUT}/pytest.xml'}
        report = dict(stage='B11', delivery_status='PASS' if delivery else 'FAIL',
            readiness_status='BLOCKED' if blockers or not delivery else 'PASS', blockers=blockers,
            branch=git(ROOT, 'branch', '--show-current'), base_commit=git(ROOT, 'rev-parse', 'HEAD'),
            remote_main_commit=git(ROOT, 'rev-parse', 'origin/main'), push_status='AWAITING_EXPLICIT_APPROVAL',
            files=files, commands=commands, live_api=live, repository=repository,
            quality_scope=quality['scope'], input_hashes={name: file_hash(ROOT / name) for name in sorted(input_names)})
        write_json(ROOT / OUTPUT / 'checks.json', report)
        write_json(ROOT / 'docs/results/final_acceptance.json',
                   assemble_acceptance(ROOT, cfg, f'{OUTPUT}/checks.json'))
    print(f"B11 delivery={report['delivery_status']}; final readiness={report['readiness_status']}")
    for blocker in report['blockers']:
        print('PENDING: ' + blocker)
    if report['delivery_status'] != 'PASS':
        return 1
    return 2 if args.require_ready and report['readiness_status'] != 'PASS' else 0


QUALITY_PATH = 'docs/results/docker/quality_full_test.json'

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        raise SystemExit(f'BLOCKED: {error}')
