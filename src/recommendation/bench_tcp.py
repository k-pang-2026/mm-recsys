"""Actual serial localhost HTTP requests, separately judged from ASGI injection."""
from __future__ import annotations
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urlencode
from src.common.artifacts import write_json,fingerprint
from src.common.schemas import RecommendResponse
from src.recommendation.datasets import read_data
from src.recommendation.bench_ranking import percentiles
from src.recommendation.scoring import policy


def benchmark_tcp(cfg,b5,output=None,selection=None):
    output=output or Path(cfg['paths']['results_dir'])/f'ranking_tcp_{cfg["scale"]}_{"b5" if b5 else "b4"}_v2.json'
    report=dict(stage='B5' if b5 else 'B4',scale=cfg['scale'],status='UNMEASURED',transport='localhost TCP HTTP',
        warmup=cfg['benchmark']['warmup'],requests=cfg['benchmark']['requests'],concurrency=1,top_n=50,
        scoring=policy(cfg['recommend'].get('scoring')),selection=str(selection) if selection else None)
    try:
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    except OSError as error:
        report['reason']=f'localhost bind unavailable: {type(error).__name__}: {error}'
        write_json(output,report);print(report['reason']);return report
    data=read_data(cfg['paths']['data_dir']);users=sorted(data['train'].user_id.unique())
    env=dict(os.environ,B_BENCH_SCORING=json.dumps(report['scoring']),B_BENCH_B5='1' if b5 else '0')
    log=Path('.team/tcp')/f'{report["stage"]}.log';log.parent.mkdir(parents=True,exist_ok=True)
    records=[];samples=[];started=time.perf_counter()
    with log.open('w') as stream:
        process=subprocess.Popen([sys.executable,'-m','uvicorn','src.recommendation.bench_app:create_bench_app','--factory',
            '--host','127.0.0.1','--port',str(port),'--workers','1'],env=env,stdout=stream,stderr=subprocess.STDOUT)
        try:
            ready=False
            while time.perf_counter()-started<60:
                if process.poll() is not None: raise RuntimeError(f'uvicorn exited {process.returncode}; log={log}')
                try:
                    with urlopen(f'http://127.0.0.1:{port}/health',timeout=1) as response:
                        ready=json.load(response)['recommend_ready']
                    if ready: break
                except OSError: pass
                time.sleep(.1)
            if not ready: raise RuntimeError(f'startup did not become ready in 60 seconds; log={log}')
            report['startup_model_loading_ms']=(time.perf_counter()-started)*1000
            for i in range(report['warmup']+report['requests']):
                uid=str(users[i%len(users)]);url=f'http://127.0.0.1:{port}/api/recommend?'+urlencode(dict(user_id=uid,top_n=50))
                begin=time.perf_counter()
                with urlopen(url,timeout=30) as response:
                    body=json.load(response);status=response.status
                elapsed=(time.perf_counter()-begin)*1000;parsed=RecommendResponse.model_validate(body)
                records.append(dict(index=i,warmup=i<report['warmup'],user_id=uid,http_status=status,http_elapsed_ms=elapsed,pipeline_latency=parsed.pipeline_latency.model_dump()))
                if i>=report['warmup'] and len(samples)<5:samples.append(body)
            measured=records[report['warmup']:]
            report.update(status='PASS' if percentiles([r['http_elapsed_ms'] for r in measured])['p95_ms']<=cfg['targets']['recommend_p95_ms'] else 'FAIL',
                errors=0,tcp_http=percentiles([r['http_elapsed_ms'] for r in measured]),native=percentiles([r['pipeline_latency']['total_ms'] for r in measured]),
                request_records=records,sample_responses=samples,data_fingerprint=data['manifest']['generation_fingerprint'],config_fingerprint=fingerprint(cfg),
                environment=dict(platform=__import__('platform').platform(),python=sys.version,threads=cfg['recommend']['ranking']['threads'],cache='no response cache'))
        except Exception as error:
            report.update(status='FAIL',reason=f'{type(error).__name__}: {error}',request_records=records,errors=1,server_log=str(log))
        finally:
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait()
    write_json(output,report);print(f'TCP={report["status"]}; output={output}');return report
