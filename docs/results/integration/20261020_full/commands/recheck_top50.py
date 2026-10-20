"""Recheck the observed top50 HTTP shape after offline full workers finish."""
import json,subprocess,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import requests

api='http://127.0.0.1:18000';container='mm-recsys-integration-20261020-api-server-1'
out=Path('docs/results/integration/20261020_full')
def health() -> dict:
    with requests.Session() as client:
        client.trust_env=False
        r=client.get(api+'/health',timeout=30);r.raise_for_status();v=r.json()
        assert v['scale']=='full' and v['model_version']=='v1.0' and v['recommend_ready'] and v['search_ready']
        client.get(api+'/ready',timeout=30).raise_for_status()
        return v
before=health();started=time.perf_counter()
def request(index: int) -> dict:
    with requests.Session() as client:
        client.trust_env=False;tick=time.perf_counter()
        r=client.get(api+'/api/recommend',params=dict(user_id=f'U{index+1:06d}',top_n=50),timeout=30)
        r.raise_for_status();rows=r.json()['recommendations']
        assert len(rows)==len({x['product_id'] for x in rows})==50
        return dict(status=r.status_code,ms=(time.perf_counter()-tick)*1000)
with ThreadPoolExecutor(max_workers=8) as pool: rows=list(pool.map(request,range(200)))
after=health()
code="from pathlib import Path;import json;print(json.dumps({n:Path('/sys/fs/cgroup',n).read_text().strip() for n in ('memory.current','memory.peak','memory.max','memory.events')}))"
resources=json.loads(subprocess.check_output(['docker','exec',container,'python','-c',code],text=True))
state=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .State}}',container],text=True))
assert state['Running'] and not state['OOMKilled']
report=dict(status='PASS',scale='full',data_fingerprint=json.loads((out/'quality_full_test.json').read_text())['data_fingerprint'],requests=200,top_n=50,http_workers=8,errors=0,seconds=time.perf_counter()-started,health_before=before,health_after=after,resources=resources,samples=rows,scope='same 200-user top50 inference request shape after offline A/B and CT workers exit; no feedback, retraining or new latency-SLA claim; original parallel OOM remains preserved')
(out/'separate_http_load_full.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print('Separate full top50 HTTP load: PASS; 200 requests, 8 workers, no OOM')
