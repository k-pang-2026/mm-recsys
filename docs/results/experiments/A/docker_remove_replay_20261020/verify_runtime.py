"""Verify the replacement live simulator and preserve historical full measurements."""
import hashlib,json,subprocess,sys,time
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
import pandas as pd
import requests
from docker.http import wait_ready
from docker.inspect_runtime import capture
from docker.runtime import runtime_config
from src.common.artifacts import file_hash,write_json
from src.ct.model_registry import bundle_hashes,ModelRegistry
from src.serving.feature_store import create_feature_store
from scripts.check_submission_evidence import check_hashes
out=Path(__file__).resolve().parent
cfg=runtime_config();root=Path(cfg['paths']['data_dir'])
wait_ready('http://127.0.0.1:8000',300)
manifest=json.loads((root/'split_manifest.json').read_text())
folder=root/'stream/live'/manifest['generation_fingerprint']
deadline=time.monotonic()+30
while True:
    files=sorted(folder.glob('events-*.parquet'),key=lambda p:p.stat().st_mtime_ns)
    if len(files)>=2:break
    assert time.monotonic()<deadline,'live simulator did not generate two small batches'
    time.sleep(1)
frame=pd.read_parquet(files[-1]);previous=pd.read_parquet(files[-2])
assert len(frame)==len(previous)==100
assert frame.event_id.is_unique and all(str(e).startswith('live-') for e in frame.event_id)
assert not set(frame.event_id)&set(previous.event_id)
supported=frame[frame.event_type.isin(['view','cart','purchase'])&frame.product_id.notna()]
user=str(supported.user_id.iloc[-1]);last_session=supported.session_id.iloc[-1]
recent=supported[supported.session_id==last_session]
views=recent[recent.event_type=='view'].product_id.tolist()
store=create_feature_store(cfg)
try:
    features=store.get_features(user)
    assert features.recent_clicks==views[-store.history_limit:]
    assert features.session_clicks==len(views)
    with store.client.pipeline() as pipe:
        for event in supported.event_id:pipe.exists(store.key('event',str(event)))
        assert all(pipe.execute())
finally:store.close()
with requests.Session() as client:
    client.trust_env=False
    response=client.get('http://127.0.0.1:8000/openapi.json',timeout=10);response.raise_for_status()
    paths=response.json()['paths']
    assert '/api/replay' not in paths and '/api/event' in paths and '/api/feedback' in paths
    assert client.post('http://127.0.0.1:8000/api/replay',json=[],timeout=10).status_code==404
    response=client.post('http://127.0.0.1:8000/api/search',json={'query_text':'black shirt','top_k':10},timeout=30)
    response.raise_for_status();assert len(response.json()['results'])==10
    response=client.get('http://127.0.0.1:8000/api/recommend',params={'user_id':'U000001','top_n':10},timeout=30)
    response.raise_for_status();assert len(response.json()['recommendations'])==10
    assert client.get('http://127.0.0.1:8501/_stcore/health',timeout=10).text.strip()=='ok'
base=Path('docs/results/integration/20261020_full')
saved=json.loads((base/'production_before_integration.json').read_text())
evaluation=json.loads((base/'preserved_full_evaluation.json').read_text())
check_hashes(Path.cwd(),evaluation['files'])
check_hashes(Path.cwd(),saved['model_metadata'])
assert file_hash(root/'split_manifest.json')==saved['data_manifest_sha256']
assert bundle_hashes(Path('models/full/v1.0'))==saved['bundle_hashes']
check_hashes(Path.cwd(),{str(root/name):sha for name,sha in manifest['file_hashes'].items()})
assert ModelRegistry(Path('models/full'),Path('docs/results/docker/runtime/full/ct_log.jsonl')).read()['active']=='v1.0'
runtime=capture('mm-recsys');assert runtime['status']=='PASS',runtime['errors']
code_paths={'api-server':['docker/serve.py','docker/http.py','src/ct/storage.py'],'simulator':['docker/simulator.py']}
container_sources={}
for service,names in code_paths.items():
    program='import hashlib,json;from pathlib import Path;print(json.dumps({p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in '+repr(names)+'}))'
    hashes=json.loads(subprocess.check_output(['docker','exec',f'mm-recsys-{service}-1','python','-c',program],text=True,timeout=15))
    check_hashes(Path.cwd(),hashes);container_sources[service]=hashes
logs=subprocess.check_output(['docker','logs','--tail','8','mm-recsys-simulator-1'],text=True,stderr=subprocess.STDOUT,timeout=10)
assert '행동 로그' in logs and '전송 완료' not in logs and '/1,000,000' not in logs
write_json(out/'runtime.json',dict(status='PASS',scale='full',data_fingerprint=manifest['generation_fingerprint'],
    checked_at=time.time(),batch_size=len(frame),event_types={str(k):int(v) for k,v in frame.event_type.value_counts().items()},
    distinct_batch_ids=True,recent_user=user,recent_session_clicks=features.session_clicks,
    redis_features_match_generated_batch=True,api_replay_removed=True,search_results=10,recommendations=10,
    dashboard_ready=True,original_evaluation_files_preserved=len(evaluation['files']),
    original_models_preserved=len(saved['bundle_hashes']),static_data_files_verified=len(manifest['file_hashes']),
    active_model='v1.0',live_log=str(files[-1]),live_log_sha256=file_hash(files[-1]),
    container_sources=container_sources,runtime=runtime,simulator_logs=logs,
    scope='actual four-service startup and generated small batches updating Redis; no full API replay, fresh training or new full-quality measurement'))
print('Four services, live batches/Redis, removed replay API, search/recommend/dashboard and frozen assets: PASS')
