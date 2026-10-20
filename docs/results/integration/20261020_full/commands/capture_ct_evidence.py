"""Preserve actual full trainer reports and observed snapshot metadata without model weights."""
import hashlib
import json
from pathlib import Path
import shutil
out=Path('docs/results/integration/20261020_full')
work=Path('models/full/.ct/runs/v1.1-3261389e')
probe=json.loads((work/'probe/registry.json').read_text())['versions']['v1.1']
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def link(path):
    return dict(source=str(path),sha256=sha(path))
reports={}
for kind in ('candidate','ranking','session'):
    source=work/'results'/f'{kind}_training_full.json'
    measured=json.loads(source.read_text())
    assert measured['scale']=='full' and measured['status']=='PASS' and measured['checkpoint_reload']=='PASS'
    dest=out/f'ct_training_{kind}_full.json'
    shutil.copyfile(source,dest)
    reports[kind]=link(dest)
manifest=Path(probe['data_path'])/'split_manifest.json'
assert json.loads(manifest.read_text())['counts']['events']>=1000000
shutil.copyfile(manifest,out/'ct_data_manifest_full.json')
lifecycle=Path('docs/results/docker/runtime/full/ct_log.jsonl')
shutil.copyfile(lifecycle,out/'ct_lifecycle_full.jsonl')
receipt=dict(status='PASS',scale='full',training_sources=reports,
    snapshot=link(out/'ct_data_manifest_full.json'),lifecycle=link(out/'ct_lifecycle_full.jsonl'),
    scope='actual completed full CT candidate/ranking/session training, checkpoint reload and observed-data manifest; no weights copied')
(out/'ct_training_sources_full.json').write_text(json.dumps(receipt,indent=2)+'\n')
print('Actual full CT trainer evidence: PASS')
