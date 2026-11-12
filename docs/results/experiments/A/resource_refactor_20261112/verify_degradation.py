"""Controlled real-training checks; never replace the production full-model registry."""
import copy
import json
import shutil
import time
from pathlib import Path
import sys
sys.path.insert(0, str(Path.cwd()))
from src.common.artifacts import write_json, file_hash
from src.ct.verify_ct import verify, verify_existing
from src.ct.model_registry import ModelRegistry
from src.ct.retrain_trigger import components, trigger, build_from_journal

root = Path('docs/results/experiments/A/resource_refactor_20261112')
work = Path('models/.ct/resource-refactor-20261112').resolve()
report_path = root / 'ct_lifecycle.json'
report = verify(work, report_path)
verify_existing(report_path)
original = ModelRegistry(work / 'models', work / 'results/ct_log.jsonl')
before_hash = file_hash(original.path)
state = original.read()
clone = work / 'degradation-models'
clone.mkdir()
for version in state['versions']:
    shutil.copytree(original.root / version, clone / version)
shutil.copy2(original.path, clone / 'registry.json')
(clone / '.ct').mkdir()
shutil.copy2(original.root / '.ct/journal.sqlite3', clone / '.ct/journal.sqlite3')
cfg = copy.deepcopy(original.record(state['active'])['config'])
cfg['paths'].update(model_dir=str(clone), results_dir=str(work / 'degradation-results'))
cfg['serving']['ct']['retry_seconds'] = 1
spec, journal, registry = components(cfg)
now = time.time()
import pandas as pd
data_path = Path(registry.record(state['active'])['data_path'])
products = pd.read_parquet(data_path / 'products.parquet').product_id.astype(str).head(50).tolist()
user = str(pd.read_parquet(data_path / 'users.parquet').user_id.iloc[0])
for i in range(spec['min_mature_requests']):
    journal.exposure(f'controlled-low-ctr:{i}', user, products, 50, state['active'],
                     now - spec['attribution_seconds'] - 1)
count = journal.count_since(registry.read()['last_success_seq'])
assert count == 0
result = trigger(cfg, lambda version, through, reg: build_from_journal(cfg, version, through, reg))
assert result['trigger_reason'] == 'performance_degradation' and result['status'] == 'PROMOTED'
assert result['new_events'] < spec['retrain_log_threshold']
registry.rollback(result['active'], state['active'], 'controlled degradation check complete')
assert file_hash(original.path) == before_hash
write_json(root / 'ct_degradation.json', dict(status='PASS', scope='controlled fixture; deliberately weak original ranker and mature zero-click observations; real three-model training, paired valid decision and isolated rollback',
    new_events=count, threshold=spec['retrain_log_threshold'], training=result,
    artifacts=dict(registry=str(registry.path), registry_sha256=file_hash(registry.path),
                   log=str(registry.log), log_sha256=file_hash(registry.log)),
    final_active=registry.read()['active'], original_lifecycle_registry_unchanged=True))
verify_existing(report_path)
print(json.dumps(dict(lifecycle=report['status'], degradation='PASS', trigger_reason=result['trigger_reason'])))
