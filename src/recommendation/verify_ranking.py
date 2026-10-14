"""Bind final B4/B5 claims to saved measured sources and current model artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.common.artifacts import file_hash,write_json
from src.common.config import load_config
from src.common.schemas import RecommendResponse
from src.recommendation.bundle_compat import verify_preservation


def summarize(cfg: dict) -> dict:
    result=Path(cfg['paths']['results_dir'])
    names=['ranking_training_full.json','session_training_full.json','ranking_full_valid.json',
           'ranking_full_test_b5.json','ranking_latency_full_b4.json','ranking_latency_full_b5.json',
           'ranking_selection_full.json','ranking_label_limitation.json','ranking_preservation.json','ranking_external_limits.json']
    documents={name:json.loads((result/name).read_text()) for name in names}
    verify_preservation(result/'ranking_preservation.json')
    ranking=documents['ranking_training_full.json']; session=documents['session_training_full.json']; test=documents['ranking_full_test_b5.json']
    selection=documents['ranking_selection_full.json']; valid=documents['ranking_full_valid.json']
    if cfg['scale']!='full' or test['scale']!='full' or test['split']!='test': raise ValueError('full frozen test required')
    model_root=Path(cfg['paths']['model_dir'])/'v1.0'
    if file_hash(model_root/'ranking/deepfm.pt')!=selection['model_sha256'] or test['ranking_model_sha256']!=selection['model_sha256']:
        raise ValueError('test/current ranking model differs from valid selection')
    if file_hash(model_root/'session/session.pt')!=selection['session_model_sha256']: raise ValueError('session selection mismatch')
    for name,digest in selection['source_hashes'].items():
        if file_hash(Path(name))!=digest: raise ValueError(f'changed frozen selection source: {name}')
    correction=selection.get('post_freeze_equivalent_correction')
    if correction:
        evidence=json.loads(Path(correction['differential_source']).read_text())
        oracle=Path('docs/results/experiments/B/reranking_frozen_oracle.py')
        predecessor=Path(correction.get('validated_predecessor','src/recommendation/reranking.py'))
        if evidence['status']!='PASS' or evidence['cases']<200 or evidence['failures'] or evidence['oracle_sha256']!=file_hash(oracle) or evidence['current_sha256']!=file_hash(predecessor):
            raise ValueError('post-freeze default-pipeline equivalence not verified')
    repair=selection.get('post_freeze_constraint_repair')
    if repair:
        evidence=json.loads(Path(repair['validation_source']).read_text())
        if evidence['status']!='PASS' or evidence['oracle_cases']<4000 or evidence['failures'] or evidence['source_sha256']!=file_hash(Path('src/recommendation/reranking.py')):
            raise ValueError('constraint repair oracle not verified')
        reused=test.get('reused_unchanged_measurements',{})
        if reused.get('source')!=repair['before_test_source'] or reused.get('sha256')!=repair['before_test_sha256'] or test.get('b5_feasible_pool_violations')!=0:
            raise ValueError('constraint repair full re-evaluation incomplete or feasible constraints violated')
    if valid['ranking_model_sha256']!=selection['model_sha256'] or ranking['best_epoch']!=selection['best_epoch']:
        raise ValueError('valid/test selection differs')
    if ranking['checkpoint_reload']!='PASS' or session['checkpoint_reload']!='PASS' or not session['strictly_preceding']:
        raise ValueError('training/reload/history check failed')
    for name in ['ranking_latency_full_b4.json','ranking_latency_full_b5.json']:
        benchmark=documents[name]
        if benchmark['warmup']!=cfg['benchmark']['warmup'] or benchmark['requests']!=cfg['benchmark']['requests'] or len(benchmark['native_elapsed_ms'])!=benchmark['requests']:
            raise ValueError('benchmark request contract mismatch')
        for response in benchmark['sample_responses']: RecommendResponse.model_validate(response)
    b4=documents['ranking_latency_full_b4.json']; b5=documents['ranking_latency_full_b5.json']; live=b5['live_flow']
    if live.get('status')!='PASS' or len(live['recent_clicks'])!=3 or not live['recommendations_changed'] or live['feedback']['duplicate_applied']:
        raise ValueError('live session/reward evidence missing')
    checks=dict(ctr_auc=test['classification']['ctr']['auc']>=cfg['targets']['auc'],
                b4_p95=max(b4['native']['p95_ms'],b4['asgi_http']['p95_ms'])<=cfg['targets']['recommend_p95_ms'],
                b5_p95=max(b5['native']['p95_ms'],b5['asgi_http']['p95_ms'])<=cfg['targets']['recommend_p95_ms'],
                schema=True,model_reload=True,session_response=True,feedback_max_and_idempotence=True,B3b_preserved=True)
    report=dict(version='b4-b5-evidence-v1',scale='full',status='PASS' if all(checks.values()) else 'FAIL',
                acceptance='UNMEASURED',B4='PASS' if checks['ctr_auc'] and checks['b4_p95'] else 'FAIL',
                B5_implementation_memory='PASS' if checks['b5_p95'] and checks['session_response'] else 'FAIL',
                common_integration='UNMEASURED',checks=checks,classification=test['classification'],
                recommendation_metrics=test['metrics'],recommendation_quality_status=test['measured_quality_status'],
                recommendation_quality_checks=test['checks'],deepfm_absolute_lift=test['deepfm_absolute_lift'],
                B4_latency=b4['native'],B5_latency=b5['native'],B5_asgi_http=b5['asgi_http'],
                coverage_users=test['coverage_users'],truth_users=test['truth_users'],data_counts=test['data_counts'],
                data_fingerprint=test['data_fingerprint'],ranking_model_sha256=selection['model_sha256'],
                session_model_sha256=selection['session_model_sha256'],
                b5_constraint_violations=test['b5_constraint_violations'],
                limits=['CVR AUC undefined: zero positives under retained 30min policy',
                        'conditional conversion probabilities unidentifiable; CTR*CVR ranking quality may regress',
                        'session metric is sampled; recorded offline sessions differ from serving inactivity TTL',
                        'real TCP/curl blocked by sandbox; ASGI injection benchmark only',
                        'C default memory/Redis MAB integration and A batch commits OPEN'],
                sources={str(result/name):file_hash(result/name) for name in names})
    if correction:
        report['sources'].update({name:file_hash(Path(name)) for name in [correction['differential_source'],'docs/results/experiments/B/reranking_frozen_oracle.py']})
        if correction.get('validated_predecessor'):
            report['sources'][correction['validated_predecessor']]=file_hash(Path(correction['validated_predecessor']))
    if repair:
        report['sources'].update({name:file_hash(Path(name)) for name in [repair['validation_source'],repair['before_test_source']]})
        report['b5_infeasible_candidate_pools']=test['b5_infeasible_candidate_pools']
        report['b5_feasible_pool_violations']=test['b5_feasible_pool_violations']
    return report


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument('--write',action='store_true'); parser.add_argument('--require-quality',action='store_true'); args=parser.parse_args()
    cfg=load_config()
    if (Path(cfg['paths']['results_dir'])/f'ranking_policy_selection_{cfg["scale"]}.json').exists():
        from src.recommendation.verify_policy import verify
        computed=verify(cfg);output=Path(cfg['paths']['results_dir'])/'ranking_metrics_v2.json'
        if args.write:write_json(output,computed)
        elif json.loads(output.read_text())!=computed:raise ValueError('ranking v2 metrics differ from measured sources')
        print(f'implementation={computed["implementation"]}; quality={computed["recommendation_quality"]}; environment={computed["environment"]}; common=UNMEASURED')
        return 1 if computed['status']!='PASS' or (args.require_quality and computed['recommendation_quality']!='PASS') else 0
    computed=summarize(cfg); output=Path(cfg['paths']['results_dir'])/'ranking_metrics.json'
    if args.write: write_json(output,computed)
    elif json.loads(output.read_text())!=computed: raise ValueError('ranking metrics differ from measured sources')
    print(f'B4={computed["B4"]}; B5 memory={computed["B5_implementation_memory"]}; quality={computed["recommendation_quality_status"]}; common integration=UNMEASURED')
    return 1 if args.require_quality and computed['recommendation_quality_status']!='PASS' else 0


if __name__=='__main__': raise SystemExit(main())
