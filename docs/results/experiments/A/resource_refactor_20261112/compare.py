import sys
from pathlib import Path
source, output = sys.argv[1:]
sys.path.insert(0, source)
import collections
import hashlib
import json
import resource
import statistics
import time
from unittest.mock import patch
import numpy as np
import pandas as pd
import torch
from src.common.config import load_config
from src.common.seed import set_seed
from src.recommendation.datasets import read_data
from src.evaluation.ab_test import create_policies, simulate
from src.common.schemas import EventRequest

cfg = load_config(str(Path(source) / 'config.yaml'))
set_seed(cfg['seed'])
reads = collections.Counter(); weights = collections.Counter()
read_parquet = pd.read_parquet; torch_load = torch.load
def read(path, *args, **kwargs):
    reads[str(path)] += 1
    return read_parquet(path, *args, **kwargs)
def load(path, *args, **kwargs):
    weights[str(path)] += 1
    return torch_load(path, *args, **kwargs)
clock = [0.]
started = time.perf_counter()
with patch('pandas.read_parquet', side_effect=read), patch('torch.load', side_effect=load):
    data = read_data(cfg['paths']['data_dir'], 'valid')
    policies, metadata = create_policies(cfg, data, clock)
setup = time.perf_counter() - started
service = policies['treatment'].service
users = sorted(service.user_rows)[:100]
for uid in users[:10]:
    service.recommend(uid, 10)
records, latencies, feature_times = [], [], []
original = service.ranking_encoder.serving
def timed(*args, **kwargs):
    start = time.perf_counter_ns()
    value = original(*args, **kwargs)
    feature_times.append((time.perf_counter_ns()-start)/1e6)
    return value
service.ranking_encoder.serving = timed
for uid in users + ['unknown-audit-user']:
    started = time.perf_counter_ns()
    response = service.recommend(uid, 10).model_dump()
    latencies.append((time.perf_counter_ns()-started)/1e6)
    response.pop('pipeline_latency'); records.append(response)
for uid in users[:10]:
    service.store.append_event(EventRequest(event_id=f'audit:{uid}', user_id=uid,
        product_id=service.table.ids[1], event_type='view', session_id=f'audit-session:{uid}'))
    response = service.recommend(uid, 10).model_dump()
    response.pop('pipeline_latency'); records.append(response)
service.ranking_encoder.serving = original
cfg['serving']['ab_test'].update(users_per_group=20, days=2)
ab = simulate(cfg, data, policies, clock)
result = dict(scope='full frozen catalog/models; 101 timed recommendations, 10 session updates; A/B 20 users per arm for 2 days',
    source=source, data_fingerprint=data['manifest']['generation_fingerprint'], bundles=metadata,
    source_hashes={str(p.relative_to(source)):hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in Path(source,'src').rglob('*.py')},
    parquet_reads=dict(reads), checkpoint_loads=dict(weights), setup_seconds=setup,
    peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
    torch_threads=torch.get_num_threads(), recommend_median_ms=statistics.median(latencies),
    recommend_p95_ms=float(np.percentile(latencies,95)), feature_median_ms=statistics.median(feature_times),
    recommendations=records, ab=ab)
Path(output).write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str))
print(json.dumps({key:result[key] for key in ('source','setup_seconds','peak_rss_mib','recommend_median_ms','recommend_p95_ms','feature_median_ms')}))
