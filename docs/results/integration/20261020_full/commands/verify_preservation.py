"""Verify original full evaluation, data and active production bundle remain unchanged."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path.cwd()))
from src.common.artifacts import file_hash,write_json
from src.ct.model_registry import bundle_hashes,ModelRegistry
from scripts.check_submission_evidence import check_hashes
root=Path.cwd();out=Path('docs/results/integration/20261020_full')
saved=json.loads((out/'production_before_integration.json').read_text())
original=json.loads((out/'preserved_full_evaluation.json').read_text())
check_hashes(root,original['files'])
check_hashes(root,saved['model_metadata'])
assert file_hash(Path('data/full/split_manifest.json'))==saved['data_manifest_sha256']
assert bundle_hashes(Path('models/full/v1.0'))==saved['bundle_hashes']
registry=ModelRegistry(Path('models/full'),Path('docs/results/docker/runtime/full/ct_log.jsonl'))
assert registry.read()['active']==saved['active_registry']=='v1.0'
registry.verify('v1.0')
manifest=json.loads(Path('data/full/split_manifest.json').read_text())
check_hashes(root,{str(Path('data/full')/name):sha for name,sha in manifest['file_hashes'].items()})
quality=json.loads((out/'quality_full_test.json').read_text())
hashes={**quality['identity']['source_hashes'],**quality['identity']['docker_sources']}
check_hashes(root,hashes)
write_json(out/'preservation_final.json',dict(status='PASS',scale='full',data_fingerprint=quality['data_fingerprint'],
    original_evaluation_files=len(original['files']),original_evaluation_unchanged=True,
    original_data_manifest_unchanged=True,data_file_hashes_verified=len(manifest['file_hashes']),
    original_model_metadata_unchanged=True,original_model_files=len(saved['bundle_hashes']),
    source_files_verified=len(hashes),active_model='v1.0',scope='post-integration preservation of user frozen evaluation and primary dataset/model bundle; no model weights committed'))
print('Original full evaluation/data/models/source preserved; active v1.0: PASS')
