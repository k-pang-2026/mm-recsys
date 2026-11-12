import json
from pathlib import Path

from src.common.artifacts import file_hash, write_json
from src.common.config import load_config
from src.evaluation import api_benchmark
from src.evaluation.reporting import environment
from src.evaluation.run_all import input_identity
from docker.serve import install_runtime_limits

cfg = load_config()
factory = api_benchmark.create_app

def deployed_factory(*args, **kwargs):
    app = factory(*args, **kwargs)
    install_runtime_limits(app, cfg)
    return app

api_benchmark.create_app = deployed_factory
result = api_benchmark.benchmark(cfg)
result['checks'] = {mode: item['http']['p95_ms'] <= cfg['targets']['recommend_p95_ms' if mode == 'recommendation' else 'search_p95_ms']
                    for mode, item in result['modes'].items()}
result['status'] = 'PASS' if all(result['checks'].values()) else 'FAIL'
result['scope'] = 'Native execution of existing docker.serve runtime hooks; no Docker daemon/container claim; frozen valid queries, 10 warmups + 100 serial requests per mode'
result['identity'] = input_identity(cfg)
result['environment'] = environment()
result['environment']['benchmark_scope'] = 'one native API process and one native Redis; other evaluation/training processes stopped'
result['runtime_source_hashes'] = {name: file_hash(Path(name)) for name in ['docker/serve.py', 'docker/vision.py', 'docker/runtime.py']}
result['verifier_sha256'] = file_hash(Path(__file__))
result['acceptance'] = 'UNMEASURED'
write_json(Path(cfg['paths']['results_dir']) / 'native_deployment_latency.json', result)
print(json.dumps(dict(status=result['status'], p95_ms={name: row['http']['p95_ms'] for name, row in result['modes'].items()})))
raise SystemExit(0 if result['status'] == 'PASS' else 1)
