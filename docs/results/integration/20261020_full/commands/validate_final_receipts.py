"""Validate final acceptance, publication/UI identity and currently running local services."""
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path.cwd()))
import requests
from src.common.config import load_config
from src.evaluation.acceptance import validate_acceptance
from scripts.check_submission_evidence import check_hashes
root=Path.cwd();out=Path('docs/results/integration/20261020_full')
cfg=load_config()
report=json.loads(Path('docs/results/final_acceptance.json').read_text())
manifest=json.loads((Path(cfg['paths']['data_dir'])/'split_manifest.json').read_text())
validate_acceptance(report,cfg,manifest,root)
receipt=json.loads((out/'dashboard_publication_receipt.json').read_text())
for key in ('archive','ui','runner','source_preservation'):
    link=receipt[key];check_hashes(root,{link['source']:link['sha256']})
assert Path(receipt['display_path']).read_bytes()==Path(receipt['archive']['source']).read_bytes()
published=json.loads(Path(receipt['display_path']).read_text())
ui=json.loads((out/'dashboard_final.json').read_text())
assert published['acceptance']==ui['acceptance_displayed']=='PASS'
assert published['integration']['checks']==report['checks']
assert published['integration']['ct']['retraining']=='RETAINED'
assert published['ab']['status']=='MEASURED' and published['ab']['inference']['cvr']['relative_lift']<0
check_hashes(root,ui['source_hashes'])
for service in ('redis','api-server','dashboard','simulator'):
    state=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .State}}',f'mm-recsys-{service}-1'],text=True,timeout=10))
    assert state['Running'] and not state['Paused'] and not state['OOMKilled']
    if service!='simulator':assert state['Health']['Status']=='healthy'
with requests.Session() as client:
    client.trust_env=False
    r=client.get('http://127.0.0.1:8000/ready',timeout=10);r.raise_for_status();assert r.json()['status']=='ready'
    r=client.get('http://127.0.0.1:8501/_stcore/health',timeout=10);r.raise_for_status();assert r.text.strip()=='ok'
print('Strict full acceptance, published PASS/AB/CT/UI hashes and four running local services: PASS')
