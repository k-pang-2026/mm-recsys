"""새 실행 결과를 PDF 요구사항에 연결합니다. 이 집계는 모델 재측정이 아닙니다."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.common.artifacts import file_hash, write_json
from src.common.console import emit_json, log, run_cli


def aggregate(root: Path) -> dict:
    sources: dict[str, str] = {}

    def read(name: str) -> dict:
        path = root / name
        sources[name] = file_hash(path)
        return json.loads(path.read_text(encoding='utf-8'))

    catalog = json.loads(Path('docs/submission/requirements_v43.json').read_text())
    data, products = read('data_audit.json'), read('catalog_contract.json')
    smoke, quality = read('smoke_full.json'), read('quality_full_test.json')
    valid, selection = read('quality_full_valid.json'), read('quality_selection_full.json')
    peer, clip = read('peer_review.json'), read('clip_item.json')
    ab, ab_check = read('ab_demo.json'), read('ab_demo_verification.json')
    drill, natural, ct = read('ct_valid_memory_drill/ct_drill.json'), read('ct_natural.json'), read('ct_execution.json')
    browser, execution = read('browser.json'), read('execution.json')
    initial, reused = read('preparation_initial.json'), read('preparation_reuse.json')
    startup_failure = read('preparation_failure.json')
    cli_failures, windows = read('cli_failures.json'), read('powershell_search.json')
    compose_json = read('compose_json_mode.json')
    utf8, repository = read('powershell_stdout.json'), read('repository.json')
    bundles = read('bundle_contracts.json')
    candidate_training, ranking_training = read('candidate_training_full.json'), read('ranking_training_full.json')
    feature = read('feature_contract.json')
    ct_before = read('ct_before_stdout.json')
    ct_watch = read('ct_watch.json')
    recovery = read('ct_recovery_full.json')
    ct_memory = read('ct_postfix_memory.json')
    ct_training_ok = recovery['status'] == 'PASS'
    for kind in ('candidate', 'ranking', 'session'):
        name = f'ct_{kind}_training_full.json'
        training = read(name)
        ct_training_ok = ct_training_ok and training['scale'] == 'full' and training['status'] == training['checkpoint_reload'] == 'PASS'
        ct_training_ok = ct_training_ok and sources[name] == natural['comparison']['training_reports'][kind]
    identity = read('source_identity.json')
    fingerprint = data['data_fingerprint']
    for value in (smoke, quality, valid, peer, clip, initial, reused, ab_check):
        if value['data_fingerprint'] != fingerprint:
            raise ValueError('다른 데이터 버전의 실행 근거가 섞였습니다.')
    if ab['identity']['data_fingerprint'] != fingerprint:
        raise ValueError('A/B 데이터 버전 불일치')
    if quality['identity'] != valid['identity'] or selection['identity'] != quality['identity']:
        raise ValueError('valid 동결 후 데이터·모델·설정·소스가 바뀌었습니다.')
    if file_hash(Path(selection['source'])) != selection['sha256']:
        raise ValueError('valid 동결 파일 checksum 불일치')
    for name, digest in {**quality['identity']['source_hashes'], **quality['identity']['docker_sources']}.items():
        path = Path(name.removeprefix('/app/'))
        if file_hash(path) != digest:
            raise ValueError(f'품질 측정 이후 소스가 바뀌었습니다: {name}')
    for name, digest in identity['source_hashes'].items():
        if file_hash(Path(name)) != digest:
            raise ValueError(f'최종 소스 fingerprint 불일치: {name}')
    cases = {}
    for name in ('pytest_release_final.xml', 'pytest_redis_final.xml', 'pytest_ct_fix.xml', 'pytest_dashboard_link.xml', 'pytest_ct_memory_fix.xml', 'pytest_child_status.xml', 'pytest_ct_valid_memory.xml'):
        sources[name] = file_hash(root / name)
        for case in ET.parse(root / name).getroot().iter('testcase'):
            cases[(case.get('classname'), case.get('name'))] = case
    # Explicit real-Redis follow-up replaces the five opt-in skips by their exact test IDs.
    test_counts = dict(tests=len(cases), **{key: sum(c.find(tag) is not None for c in cases.values())
        for key, tag in [('failures','failure'), ('errors','error'), ('skipped','skipped')]})
    test_names = {c.get('name', '') for c in cases.values()}
    tests_ok = test_counts['tests'] > 0 and not any(test_counts[k] for k in ('failures', 'errors', 'skipped'))
    mypy = (root / 'mypy_final.log').read_text()
    sources['mypy_final.log'] = file_hash(root / 'mypy_final.log')
    engineering_ok = tests_ok and 'Success: no issues found' in mypy
    docs = ['README.md', 'docs/contracts.md', 'docs/submission/contributions.json', 'docs/requirements_completion.md']
    engineering = dict(status='PASS' if engineering_ok else 'FAIL', tests=test_counts, mypy=mypy.strip(),
        packages=smoke['benchmark']['environment']['packages'], documentation={p: file_hash(Path(p)) for p in docs},
        repository=repository, scope='new tests and container measurements; contribution document inspected, not a new attribution claim')
    write_json(root / 'engineering.json', engineering)
    for name in ('text', 'image', 'hybrid', 'recommend', 'session'):
        value = read(f'demo_{name}.json')
        if value != read(f'demo_{name}_stdout.json'):
            raise ValueError(f'CLI stdout와 저장 원본이 다릅니다: {name}')
    write_json(root / 'cli.json', dict(status=cli_failures['status'], real_http=True,
        commands=[c for c in execution['commands'] if c['name'].startswith('demo_')],
        failures=cli_failures, windows=windows, compose_json=compose_json, json_stdout_matches_saved_files=True))
    compose_ok = (initial['status'] == reused['status'] == startup_failure['status'] == 'PASS'
        and all(reused['artifact_state_before'].values()) and len(reused['stages']) == 6
        and all(s['exit_code'] == 0 for s in reused['stages'])
        and all(c['exit_code'] == 0 for c in ct['commands'] if c['name'].startswith('legacy_')))
    write_json(root / 'compose_runtime.json', dict(status='PASS' if compose_ok else 'FAIL',
        initial_seconds=initial['elapsed_seconds'], reused_seconds=reused['elapsed_seconds'],
        startup_failure=startup_failure, commands=[c for c in execution['commands'] if c['name'].startswith('compose_')]
        + [c for c in ct['commands'] if c['name'].startswith('legacy_')]))
    metrics = {m['name']: m for m in quality['metrics']}
    def metric(*names: str) -> bool:
        return all(metrics[n]['status'] == 'PASS' for n in names)
    def peer_checks(prefix: str) -> bool:
        selected = [v for k, v in peer['checks'].items() if k.startswith(prefix)]
        return bool(selected) and all(selected)
    bench = smoke['benchmark']
    checks = dict(
        D1=products['count'] >= 50000 and products['missing_images'] == 0 and not any(products['nulls'].values()),
        D2=set(products['hierarchy_counts']) == {'category_l1', 'category_l2', 'category_l3'},
        D3=data['counts']['users'] >= 10000 and data['checks']['six_personas'],
        D4=all(data['checks'][k] for k in ('category_difference', 'price_sensitivity', 'conversion_difference', 'brand_loyalty')),
        D5=data['counts']['events'] >= 1000000 and data['checks']['event_types'],
        D6=tests_ok and 'test_yaml_persona_ratios_and_taxonomy_change_generated_assets' in test_names,
        S1=all(v['dimension'] == 512 and abs(v['norm']-1) < 1e-5 for v in clip['vectors'].values()),
        S2=smoke['status'] == 'PASS' and all(read(f'demo_{m}.json')['search_type'] == m for m in ('text','image','hybrid')),
        S3=any(v['content'].get('identity', {}).get('faiss', {}).get('type') in ('HNSW','IVF-PQ') for v in bundles.values()),
        S4=metric('search_p95_ms'), S5=metric('mrr','ndcg_at_10'),
        R1=tests_ok and feature['user_fields'] == ['age_group','gender']
            and candidate_training['sampling']['strictly_preceding_history'] and not feature['item_id_residual'],
        R2='item_index.faiss' in products['candidate_files'] and quality['candidate_count_pass']
            and {'category_l1','category_l2','category_l3','brand','color','style'} == set(feature['item_fields'])
            and feature['price_std'] > 0,
        R3=quality['candidate_count_pass'] and metric('candidate_p95_ms'), R4=metric('recall_at_300'),
        R5=set(quality['recommendation']['classification']) >= {'ctr','cvr'}, R6=metric('auc'),
        R7=peer_checks('cold_start_'), R8=peer_checks('exploration_'), R9=peer_checks('new_item_'),
        R10=peer_checks('diversity_') and len([k for k in peer['checks'] if k.startswith('diversity_')]) >= 3,
        R11=peer_checks('session_') and read('session_training_full.json')['scale'] == 'full',
        R12=metric('hit_rate_at_50','ndcg_at_50','coverage'), R13=metric('recommend_p95_ms'),
        F1=metric('feature_p95_ms') and peer_checks('session_redis'), F2=compose_ok, F3=compose_ok,
        A1=ab_check['status'] == 'PASS', A2=ab_check['status'] == 'PASS', A3=browser['status'] == 'PASS',
        C1=drill['checks']['alert'] and ct_watch['status'] == 'PASS',
        C2=ct['status'] == ct['uninterrupted_full_ct_after_memory_fix'] == 'PASS' and ct_training_ok
            and natural['new_events'] >= ct_before['threshold'] == 10000
            and 'oom_kill 0' in ct_memory['memory.events'] and int(ct_memory['memory.max']) == 4 * 1024**3,
        C3=drill['checks']['no_improvement_retained'] and natural['comparison']['split'] == 'valid'
            and natural['comparison']['baseline']['validation_fingerprint'] == natural['comparison']['candidate']['validation_fingerprint'],
        C4=all(drill['checks'][k] for k in ('atomic_http_reload','rollback','real_three_model_retraining','new_events_consumed_once')),
        P1=data['seed'] == 42 and data['split_ratios'] == dict(train=.8,valid=.1,test=.1),
        P2=candidate_training['sampling']['random_negatives_per_positive'] == 4
            and all('persona' in v['excluded_inputs'] and v['rows'] > v['clicks'] for v in ranking_training['labels'].values()),
        P3=bool(quality['search']['bm25']) and bool(quality['recommendation']['relative_lift']),
        P4=quality['recommendation']['contract'].endswith('top50'),
        P5=not quality['test_used_for_selection'] and quality['recommendation']['cohort']['total_users'] == data['counts']['users'],
        P6=all(v['warmup'] == 10 and v['requests'] == 100 for v in bench['modes'].values())
            and bench['feature']['warmup'] == 10 and bench['feature']['requests'] == 100
            and bench['candidate']['warmup'] == 10 and bench['candidate']['calls'] == 100,
        X1=engineering_ok, X2=not bench['environment']['gpu_used'] and clip['encoder']['device'] == 'cpu',
        X3=engineering_ok, X4=engineering_ok and all(Path(p).is_file() for p in docs),
        X5=repository['public'] is True, U1=data['status'] == 'PASS', U2=bool(clip['encoder']['model_revision']),
        U3=cli_failures['status'] == compose_json['status'] == 'PASS', U4=browser['checks']['actual_click_comparison'],
        U5=utf8['status'] == windows['status'] == 'PASS')
    if set(checks) != {r['id'] for r in catalog['requirements']}:
        raise ValueError('필수 요구사항과 집계 검사 목록이 다릅니다.')
    entries = []
    for requirement in catalog['requirements']:
        path = root / requirement['evidence']
        entries.append(dict(requirement, status='PASS' if checks[requirement['id']] else 'FAIL',
                            evidence_sha256=file_hash(path)))
    peers = {question: dict(status='PASS' if all(checks[i] for i in ids) else 'FAIL', requirements=ids)
             for question, ids in catalog['peer_review'].items()}
    result = dict(status='PASS' if all(checks.values()) and execution['status'] == ct['status'] == 'PASS' else 'FAIL',
        generated_at=datetime.now(timezone.utc).isoformat(), data_fingerprint=fingerprint,
        git_base_sha=identity['git_head'], source_identity_sha256=file_hash(root / 'source_identity.json'),
        scope='current user requirements 1–10; aggregation of this execution; not a rewrite of historical B11 acceptance',
        interpretation=catalog['interpretation'], requirements=entries, peer_review=peers,
        metrics=quality['metrics'], cvr=quality['recommendation']['classification']['cvr'],
        ab=ab['inference'], ct_natural_decision=natural['status'], evidence_hashes=sources,
        limitations=['A/B is synthetic, 100 users per arm for 7 days; not a production lift claim',
            'initial full CT paired validation hit the 4GB limit; failure and verified recovery preserved separately from the subsequent uninterrupted full CT rerun',
            'a later comparison was killed by host-wide memory exhaustion below the container limit; unused train-label allocation removed, service processes restarted and original failure preserved',
            'normal online attribution was UNMEASURED before maturity; alert/promotion/rollback use a separate controlled drill',
            'isolated CT drill starts from a deliberately constant ranker; no full-model improvement is inferred',
            'single-deployment warm single-request latency; first-request and multi-deployment load not measured',
            'external datasets optional by recorded instructor decision; remote publication not performed'])
    write_json(root / 'requirements.json', result)
    for row in entries:
        message = row['requirement']
        if row['status'] != 'PASS':
            message += f" / 원인: 필수 검사 미충족 / 다음 조치: {row['evidence']}의 원본 결과를 확인하세요."
        log('요구사항', row['id'], message, status='통과(PASS)' if row['status'] == 'PASS' else '실패(FAIL)')
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, default=Path('docs/results/integration/20261107_requirements'))
    result = aggregate(parser.parse_args().results)
    emit_json(dict(status=result['status'], requirements=len(result['requirements']), peer_questions=len(result['peer_review'])))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(run_cli(main, '요구사항 집계', '누락·불일치한 원본 실행 근거를 확인하세요. 과거 PASS로 대체하지 마세요.'))
