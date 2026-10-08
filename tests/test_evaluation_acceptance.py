import copy
from pathlib import Path
import pytest
from src.common.artifacts import file_hash
from src.common.config import load_config
from src.evaluation.acceptance import validate_acceptance


def evidence(tmp_path):
    source=tmp_path/'measured.json';source.write_text('{"fixture":"validation only"}')
    cfg=copy.deepcopy(load_config());cfg['scale']='full'
    manifest={'scale':'full','generation_fingerprint':'fixture','counts':{'products':50000,'users':10000,'events':1000000}}
    entry={'status':'PASS','source':source.name,'sha256':file_hash(source)}
    metrics={key:{**entry,'value':value,'split':'benchmark' if key.endswith('_ms') else 'test'}
             for key,value in {**cfg['targets'],'candidate_count':300}.items()}
    checks={key:{**entry,'exit_code':0} for key in ['docker_reproduction','api_schemas','ab_statistics','session_response','ct_retrain_and_rollback','submission']}
    return cfg,manifest,{'scale':'full','status':'PASS','data_fingerprint':'fixture','metrics':metrics,'checks':checks}


def test_final_acceptance_requires_actual_thresholds_and_evidence(tmp_path):
    cfg,manifest,report=evidence(tmp_path)
    validate_acceptance(report,cfg,manifest,tmp_path)
    report['metrics']['recall_at_300']['value']=.2999
    with pytest.raises(ValueError,match='below acceptance'):validate_acceptance(report,cfg,manifest,tmp_path)


@pytest.mark.parametrize('defect',['missing_metric','nan','dev','wrong_dataset','missing_docker','modified_evidence'])
def test_incomplete_final_acceptance_cannot_publish(tmp_path,defect):
    cfg,manifest,report=evidence(tmp_path)
    if defect=='missing_metric':del report['metrics']['auc']
    elif defect=='nan':report['metrics']['auc']['value']=float('nan')
    elif defect=='dev':manifest['scale']='dev'
    elif defect=='wrong_dataset':report['data_fingerprint']='stale'
    elif defect=='missing_docker':report['checks']['docker_reproduction']['status']='UNMEASURED'
    else:(tmp_path/'measured.json').write_text('changed after validation')
    with pytest.raises(ValueError):validate_acceptance(report,cfg,manifest,tmp_path)
