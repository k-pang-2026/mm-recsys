"""Assemble only executed and hash-validated current full integration receipts."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path.cwd()))
from scripts.check_submission_evidence import source,validate_separated_ct,collect_integration_checks
from src.common.artifacts import file_hash,write_json
root=Path.cwd();out=Path('docs/results/integration/20261020_full')
quality=json.loads((out/'quality_full_test.json').read_text())
fp=quality['data_fingerprint']
def link(name):return dict(source=str(out/name),sha256=file_hash(out/name))
ct=dict(schema='ct-full-separated-lifecycle-v1',status='PASS',scale='full',data_fingerprint=fp,
    natural=link('ct_full.json'),controlled_lifecycle=link('ct_controlled_lifecycle_full.json'),
    training=link('ct_training_sources_full.json'),candidate_validation=link('ct_candidate_valid_full.json'),
    configuration=link('configuration_full.json'),controlled_reload=link('ct_controlled_reload_full.jsonl'),
    scope='actual full three-model retraining naturally RETAINED; exact trained candidate in independent full-size constant-initial fixture for real HTTP promotion/reload/rollback; primary v1.0 unchanged',
    limitations=['natural improvement below original .001 guard; no production model improvement established',
        'controlled initial ranker fault is functional coverage, not a natural promotion',
        'original 4GiB comparison OOM preserved; verified artifacts resumed separately after Docker memory recovery',
        'scripted view observations; monitor maturity advances query clock only; CT selection uses valid, not test'])
validate_separated_ct(root,ct,fp)
write_json(out/'ct_acceptance_full.json',ct)
if '--ct-only' in sys.argv:
    print('Actual full natural CT and separate full lifecycle evidence validated: PASS')
    raise SystemExit(0)
checks={key:source(root,str(out/name),status='PASS',exit_code=0) for key,name in (
    ('docker_reproduction','fresh_checkout.json'),('api_schemas','current_benchmark/smoke_full.json'),
    ('ab_statistics','ab_acceptance_full.json'),('session_response','mab_full.json'),
    ('ct_retrain_and_rollback','ct_acceptance_full.json'))}
receipt=dict(status='PASS',scale='full',data_fingerprint=fp,checks=checks,limitations=[
    'Original user full valid/test/latency evidence preserved and reused; current supplemental HTTP benchmark is a separate measurement.',
    'Synthetic 5000/arm 30-day A/B CVR relative change -30.6084%; no positive production effect claimed.',
    'Natural full CT retained v1.0; separate full-size constant-initial functional drill covers actual promotion/reload/rollback using the exact trained candidate.',
    'Parallel two-API plus A/B/CT API OOM and monolithic 4GiB CT comparison OOM remain preserved in parallel_load_failure.json and ct_memory_failure.json; sequential follow-ups resolve only their documented scopes.',
    'Docker Desktop was restarted after WSL memory/swap saturation; stored data, models and frozen evaluation were retained.',
    'Current benchmark uses one deployment with replay paused, no A/B/CT worker; no multi-deployment training/load latency guarantee.',
    'Dashboard Streamlit AppTest and real API forms verified; browser pixel rendering and live-user lift unmeasured.',
    'Current INTEGRATE commit remote publication needs fresh explicit approval; external submission URL entry not performed.'])
collect_integration_checks(root,receipt,fp)
write_json(out/'integration_checks.json',receipt)
print('All five executed full integration checks validated: PASS')
