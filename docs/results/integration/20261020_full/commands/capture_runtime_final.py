"""Capture restored primary services, Korean startup logs and frozen deployed source identity."""
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path.cwd()))
from docker.inspect_runtime import capture
from src.common.artifacts import write_json,file_hash
out=Path('docs/results/integration/20261020_full')
runtime=capture('mm-recsys')
assert runtime['status']=='PASS',runtime['errors']
assert not runtime['services']['simulator']['state']['Paused']
write_json(out/'primary_runtime_final.json',runtime)
for service in ('api-server','dashboard','simulator'):
    row=runtime['services'][service]
    started=row['state']['StartedAt']
    log=subprocess.check_output(['docker','logs','--since',started,row['id']],stderr=subprocess.STDOUT,text=True,timeout=20)
    (out/'commands'/f'primary_{service}_final.txt').write_text(log)
quality=json.loads((out/'quality_full_test.json').read_text())
expected={**quality['identity']['source_hashes'],**quality['identity']['docker_sources']}
code='import hashlib,json;from pathlib import Path;print(json.dumps({p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in '+repr(list(expected))+'}))'
actual=json.loads(subprocess.check_output(['docker','exec','mm-recsys-api-server-1','python','-c',code],text=True,timeout=20))
assert actual==expected
write_json(out/'primary_sources_final.json',dict(status='PASS',source_hashes=actual,scope='actual restored API image frozen model/measurement core and Docker source identity; host publisher and dashboard verified separately'))
api=(out/'commands/primary_api-server_final.txt').read_text()
dashboard=(out/'commands/primary_dashboard_final.txt').read_text()
simulator=(out/'commands/primary_simulator_final.txt').read_text()
assert all(text in api for text in ('FAISS 인덱스 로딩 완료 (50,000 상품)','Two-Tower 모델 로딩 완료','DeepFM Ranking 모델 로딩 완료','http://localhost:8000'))
assert 'http://localhost:8501' in dashboard
assert '행동 로그' in simulator
print('Four primary services running, simulator unpaused, API ready, frozen source and Korean logs: PASS')
