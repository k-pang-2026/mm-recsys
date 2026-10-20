"""Verify immutable execution receipts and their exact current source identities."""
import hashlib,json,sys,xml.etree.ElementTree as ET
from pathlib import Path
root=Path.cwd();sys.path.insert(0,str(root))
from src.common.artifacts import file_hash
folder=Path(__file__).resolve().parent
report=json.loads(folder.with_suffix('.json').read_text())
assert report['status']=='PASS' and report['acceptance']=='UNMEASURED'
for name,digest in {**report['source_hashes'],**report['evidence_hashes']}.items():
    assert file_hash(root/name)==digest,name
suites=list(ET.parse(folder/'pytest.xml').getroot().iter('testsuite'))
counts={k:sum(int(s.get(k,'0')) for s in suites) for k in ('tests','failures','errors','skipped')}
assert counts=={k:report['checks']['pytest'][k] for k in counts}
assert counts['tests']==385 and counts['failures']==counts['errors']==counts['skipped']==0
assert 'Success: no issues found in 12 source files' in (folder/'mypy.txt').read_text()
assert 'No broken requirements found.' in (folder/'pip_check.txt').read_text()
runtime=json.loads((folder/'runtime.json').read_text())
assert runtime['status']=='PASS' and runtime['api_replay_removed']
assert runtime['redis_features_match_generated_batch'] and runtime['distinct_batch_ids']
assert runtime['original_evaluation_files_preserved']==7 and runtime['original_models_preserved']==12
for hashes in runtime['container_sources'].values():
    for name,digest in hashes.items():assert file_hash(root/name)==digest,name
assert not (root/'docker/replay.py').exists()
print('385 regression cases, runtime/Redis/API checks, frozen asset receipts and exact source fingerprints: PASS')
