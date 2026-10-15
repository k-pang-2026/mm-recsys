"""Separate implementation, recommendation quality, environment and integration gates."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
from src.common.artifacts import file_hash,write_json,fingerprint
from src.common.config import load_config
from src.common.schemas import RecommendResponse
from src.recommendation.bundle_compat import verify_preservation
from src.recommendation.eval_policy import choose,quality_checks
from src.recommendation.scoring import policy


def classification_source(report):
    reuse=report['classification_reuse'];path=Path(reuse['source'])
    if file_hash(path)!=reuse['sha256']:raise ValueError('reused classification source changed')
    old=json.loads(path.read_text())
    if old['classification']!=report['classification'] or old['data_fingerprint']!=report['identity']['data_fingerprint'] or old['ranking_model_sha256']!=report['identity']['ranking_model_sha256']:
        raise ValueError('classification reuse differs from frozen model/data/evidence')
    return path


def verify(cfg):
    root=Path(cfg['paths']['results_dir'])
    selection_path=root/f'ranking_policy_selection_{cfg["scale"]}.json'
    selection=json.loads(selection_path.read_text())
    valid_path=Path(selection['valid_report']);valid=json.loads(valid_path.read_text())
    if file_hash(valid_path)!=selection['valid_report_sha256']: raise ValueError('valid report changed after selection')
    if valid['split']!='valid' or valid['identity']!=selection['identity']: raise ValueError('valid selection identity mismatch')
    expected=choose(valid['rows'])
    if expected!=selection['selected'] or selection['status']!=('SELECTED' if expected else 'WITHHELD'):
        raise ValueError('policy does not follow frozen valid eligibility/selection rule')
    for name,digest in selection['source_hashes'].items():
        if file_hash(Path(name))!=digest: raise ValueError(f'changed frozen policy source: {name}')
    if cfg['scale']!='full' or selection['identity']['scale']!='full': raise ValueError('full evaluation required')
    if {k:cfg['targets'][k] for k in selection['thresholds']}!=selection['thresholds']: raise ValueError('thresholds changed')
    if (valid['coverage_users'],valid['catalog_items'])!=(10000,50000):raise ValueError('valid Coverage cohort/denominator changed')
    for row in valid['rows']:
        if not np.isclose(row['metrics']['coverage'],row['metrics']['unique_recommended_items']/50000):raise ValueError('valid Coverage numerator/denominator mismatch')
        if quality_checks(row['metrics'],cfg,row['diagnostics']['feasible_pool_violations'])!=row['checks']: raise ValueError('valid quality checks differ from metrics')
    identity=selection['identity'];model_root=Path(cfg['paths']['model_dir'])/'v1.0'
    for section,prefix in [('candidate_artifact_hashes',''),('ranking_artifact_hashes','ranking/'),('session_artifact_hashes','session/')]:
        for name,digest in identity[section].items():
            if file_hash(model_root/(prefix+name))!=digest: raise ValueError(f'model/index/features changed: {prefix}{name}')
    manifest=json.loads((Path(cfg['paths']['data_dir'])/'split_manifest.json').read_text())
    if identity['data_fingerprint']!=manifest['generation_fingerprint'] or identity['data_hashes']!=manifest['file_hashes']:
        raise ValueError('data manifest changed')
    if identity['inference_fingerprint']!=fingerprint({k:v for k,v in cfg['recommend'].items() if k not in ('scoring','enable_reranking','record_exposures')}):
        raise ValueError('inference config changed')
    verify_preservation()
    sources=[selection_path,valid_path,classification_source(valid)]
    tests={};quality='WITHHELD';classification=valid['classification']
    if selection['status']=='SELECTED':
        test_path=root/f'ranking_policy_{cfg["scale"]}_test.json';test=json.loads(test_path.read_text());sources.append(test_path)
        sources.append(classification_source(test))
        if test['selection_sha256']!=file_hash(selection_path) or test['identity']!=identity or test['split']!='test' or len(test['rows'])!=1:
            raise ValueError('test is not the single frozen valid policy')
        row=test['rows'][0]
        if row['name']!=expected['name'] or row['policy']!=expected['policy']: raise ValueError('test policy differs from valid selection')
        if quality_checks(row['metrics'],cfg,row['diagnostics']['feasible_pool_violations'])!=row['checks']: raise ValueError('test quality checks differ from metrics')
        if not np.isclose(row['metrics']['coverage'],row['metrics']['unique_recommended_items']/50000):raise ValueError('test Coverage numerator/denominator mismatch')
        quality='PASS' if all(row['checks'].values()) else 'FAIL'
        if quality!=test['quality_status']: raise ValueError('incorrect test quality status')
        if (test['coverage_users'],test['catalog_items'])!=(10000,50000): raise ValueError('full Coverage cohort/denominator changed')
        tests=row;classification=test['classification']
        if policy(cfg['recommend'].get('scoring'))!=expected['policy']: raise ValueError('operating API config differs from selected policy')
    latencies={};latency_checks={};live_pass=False
    for stage in ['b4','b5']:
        path=root/f'ranking_latency_full_{stage}_v2.json'
        if not path.exists():latency_checks[stage]=False;continue
        doc=json.loads(path.read_text());sources.append(path);latencies[stage]=dict(native=doc['native'],asgi_http=doc['asgi_http'],startup_model_loading_ms=doc['startup_model_loading_ms'])
        if (doc['warmup'],doc['requests'],doc['concurrency'],doc['top_n'])!=(10,100,1,50):raise ValueError('latency contract changed')
        if len(doc['request_records'])!=110 or len(doc['native_elapsed_ms'])!=100 or len(doc['asgi_http_elapsed_ms'])!=100 or doc['errors']!=0:
            raise ValueError('latency raw requests missing or errors found')
        if doc['scoring']!=policy(cfg['recommend'].get('scoring')): raise ValueError('benchmark policy differs from API')
        if doc['data_fingerprint']!=identity['data_fingerprint']: raise ValueError('benchmark data differs from frozen policy')
        for name,digest in doc['source_hashes'].items():
            if file_hash(Path(name))!=digest:raise ValueError('benchmark source changed')
        for i,record in enumerate(doc['request_records']):
            if record['index']!=i or record['warmup']!=(i<10) or record['http_status']!=200: raise ValueError('raw request contract changed')
            if i>=10 and (record['http_elapsed_ms']!=doc['asgi_http_elapsed_ms'][i-10] or record['pipeline_latency']['total_ms']!=doc['native_elapsed_ms'][i-10]):raise ValueError('raw request/latency array mismatch')
        for name,digest in doc['artifact_hashes'].items():
            if file_hash(model_root/name)!=digest:raise ValueError('benchmark model identity changed')
        for name,values in [('native',doc['native_elapsed_ms']),('asgi_http',doc['asgi_http_elapsed_ms'])]:
            for percentile in [50,95,99]:
                if not np.isclose(doc[name][f'p{percentile}_ms'],np.percentile(values,percentile),rtol=0,atol=1e-9):raise ValueError('latency percentile differs from raw requests')
        for response in doc['sample_responses']: RecommendResponse.model_validate(response)
        latency_checks[stage]=max(doc['native']['p95_ms'],doc['asgi_http']['p95_ms'])<=cfg['targets']['recommend_p95_ms']
        if (doc['status']=='PASS')!=latency_checks[stage]:raise ValueError('latency status differs from measured percentiles')
        if stage=='b5':
            live=doc['live_flow'];live_pass=live.get('status')=='PASS' and len(live['recent_clicks'])==3 and live['recommendations_changed'] and not live['feedback']['duplicate_applied']
            if not live_pass:raise ValueError('session/feedback evidence incomplete')
    ctr=classification['ctr']['auc']
    implementation=all(latency_checks.values()) and live_pass and ctr is not None and ctr>=cfg['targets']['auc']
    tcp_path=root/'ranking_tcp_full_b5_v2.json'
    tcp=json.loads(tcp_path.read_text()) if tcp_path.exists() else {'status':'UNMEASURED','reason':'not executed'}
    if tcp_path.exists():sources.append(tcp_path)
    return dict(version='b4-b5-evidence-v2',status='PASS' if implementation else 'FAIL',acceptance='UNMEASURED',
        implementation='PASS' if implementation else 'FAIL',recommendation_quality=quality,environment=dict(asgi='PASS' if all(latency_checks.values()) else 'FAIL',tcp=tcp['status']),
        common_integration='UNMEASURED',policy_selection=selection['status'],policy=expected['policy'] if expected else None,
        valid_comparison=[{k:r[k] for k in ['name','metrics','checks']} for r in valid['rows']],test=tests,classification=classification,
        latencies=latencies,checks=dict(B3b_preserved=True,model_feature_hashes=True,policy_selection_rule=True,single_frozen_test=bool(tests),**latency_checks),
        test_previously_observed=True,limits=['30min CVR policy retained; zero purchase positives and undefined CVR AUC',
            'ASGI B memory injection only; default C store MAB/Redis/Docker integration remains OPEN',
            'PR8 merge/latest main synchronization not verified: GitHub API network unavailable'],
        sources={str(p):file_hash(p) for p in sources})


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--write',action='store_true');parser.add_argument('--require-quality',action='store_true');args=parser.parse_args()
    cfg=load_config();report=verify(cfg);output=Path(cfg['paths']['results_dir'])/'ranking_metrics_v2.json'
    if args.write:write_json(output,report)
    elif json.loads(output.read_text())!=report:raise ValueError('summary differs from measured sources')
    print(f'implementation={report["implementation"]}; quality={report["recommendation_quality"]}; environment={report["environment"]}; common=UNMEASURED')
    return 1 if report['status']!='PASS' or (args.require_quality and report['recommendation_quality']!='PASS') else 0

if __name__=='__main__':raise SystemExit(main())
