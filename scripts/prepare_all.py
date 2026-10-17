"""Single-writer, checksum-verified preparation; never overwrite frozen data/models."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.common.artifacts import file_hash, fingerprint, write_json
from docker.runtime import runtime_config, config_path
from src.search.locking import writer_lock


def prefetch(cfg: dict) -> None:
    # Search's local_files_only policy remains intact after this explicit download.
    from huggingface_hub import hf_hub_download, snapshot_download
    from huggingface_hub.errors import LocalEntryNotFoundError
    spec = cfg['search']
    try:
        for name in ('config.json', 'preprocessor_config.json', 'tokenizer_config.json',
                     'vocab.json', 'merges.txt', 'pytorch_model.bin'):
            hf_hub_download(spec['clip_model'], name, revision=spec['clip_revision'], local_files_only=True)
        print('REUSE: complete pinned CLIP cache (offline)', flush=True)
        return
    except LocalEntryNotFoundError:
        pass
    snapshot_download(spec['clip_model'], revision=spec['clip_revision'],
                      allow_patterns=['*.json', '*.txt', 'pytorch_model.bin', '*.safetensors'])


def stage(cfg: dict, name: str) -> None:
    if name == 'data':
        from src.simulator.generate import generate
        generate(cfg)
    elif name == 'embeddings':
        from src.search.build_embeddings import build_embeddings
        prefetch(cfg)
        build_embeddings(cfg)
    elif name == 'indexes':
        from src.search.build_index import build_indexes
        import faiss
        folder = build_indexes(cfg)
        for mode in ('text', 'image', 'hybrid'):
            index = faiss.read_index(str(folder / f'{mode}.faiss'))
            print(f'LOADED FAISS {mode}: vectors={index.ntotal}, dim={index.d}', flush=True)
    elif name == 'recommendation':
        from src.recommendation.service import create_service
        from src.serving.memory_store import MemoryFeatureStore
        from src.ct.training import train_all
        from src.ct.model_registry import REQUIRED
        folder = Path(cfg['paths']['model_dir']) / 'v1.0'
        if folder.exists():
            # A partial or stale model fails visibly; trainers never overwrite it.
            missing = [p for p in REQUIRED if not (folder / p).is_file()]
            if missing:
                raise ValueError(f'Incomplete recommendation bundle: {missing}; use a new model path')
            if create_service(cfg, MemoryFeatureStore()) is None:
                raise ValueError('incompatible recommendation bundle')
            print('REUSE: fully loaded compatible recommendation bundle', flush=True)
        else:
            import uuid
            work = Path(cfg['paths']['model_dir']) / '.docker' / f'train-{uuid.uuid4().hex[:12]}'
            _, bundle = train_all(cfg, work)
            # No other preparation or CT trainer may publish this initial version.
            bundle.rename(folder)
            if create_service(cfg, MemoryFeatureStore()) is None:
                raise ValueError('newly prepared recommendation bundle did not load')
    elif name == 'warmup':
        from src.serving.feature_store import RedisFeatureStore, create_feature_store
        from src.serving.warmup_features import warmup
        from src.ct.bootstrap import bootstrap
        store = create_feature_store(cfg)
        if not isinstance(store, RedisFeatureStore):
            raise ValueError('Docker requires Redis')
        try:
            print(json.dumps(warmup(cfg, store)), flush=True)
        finally:
            store.close()
        if cfg['serving']['ct']['enabled']:
            state = bootstrap(cfg)
            from src.ct.retrain_trigger import components
            from src.serving.model_loader import load_record
            from src.serving.memory_store import MemoryFeatureStore
            _, _, registry = components(cfg)
            record = registry.verify(state['active'])
            if ({k:v for k,v in record['config']['recommend'].items() if k!='scoring'}
                    != {k:v for k,v in cfg['recommend'].items() if k!='scoring'}):
                raise ValueError('active release uses a different recommendation configuration; explicit new release required')
            current = json.loads((Path(cfg['paths']['data_dir']) / 'split_manifest.json').read_text())
            active = json.loads((Path(record['data_path']) / 'split_manifest.json').read_text())
            if active['file_hashes']['products.parquet'] != current['file_hashes']['products.parquet']:
                raise ValueError('active recommendation catalog differs from search; coordinated migration required')
            load_record(registry, state['active'], MemoryFeatureStore(),scoring=cfg['recommend'].get('scoring'))
    else:
        raise ValueError(f'unknown preparation stage: {name}')


def prepare(cfg: dict) -> dict:
    import yaml
    started = time.perf_counter()
    folder = Path(cfg['paths']['model_dir']) / '.docker'
    folder.mkdir(parents=True, exist_ok=True)
    output = Path(cfg['paths']['results_dir']) / 'preparation.json'
    with writer_lock(folder / 'prepare.lock'):
        runtime = config_path(cfg)
        temporary = runtime.with_suffix('.tmp')
        temporary.write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding='utf-8')
        temporary.replace(runtime)
        env = {**os.environ, 'CONFIG_PATH': str(runtime), 'SCALE': cfg['scale'],
               'PYTHONHASHSEED': str(cfg['seed'])}
        before_state = dict(data_manifest=(Path(cfg['paths']['data_dir']) / 'split_manifest.json').exists(),
            search_indexes=(Path(cfg['paths']['model_dir']) / cfg['search']['artifact_subdir'] / 'indexes_current.json').exists(),
            recommendation=(Path(cfg['paths']['model_dir']) / 'v1.0').exists())
        steps = []
        for name in ('data', 'embeddings', 'indexes', 'recommendation', 'warmup'):
            before = time.perf_counter()
            command = [sys.executable, str(Path(__file__).resolve()), '--stage', name]
            print(f'PREPARE {name}', flush=True)
            result = subprocess.run(command, env=env, timeout=float(os.getenv('PREPARE_TIMEOUT_SECONDS', '21600')))
            steps.append(dict(stage=name, command=command, exit_code=result.returncode,
                              seconds=time.perf_counter() - before))
            if result.returncode:
                write_json(output, dict(status='FAIL', scale=cfg['scale'], stages=steps))
                raise RuntimeError(f'preparation failed at {name}: exit {result.returncode}')
        manifest = Path(cfg['paths']['data_dir']) / 'split_manifest.json'
        report = dict(status='PASS', acceptance='UNMEASURED', scale=cfg['scale'],
                      data_fingerprint=json.loads(manifest.read_text())['generation_fingerprint'],
                      manifest_sha256=file_hash(manifest), config_fingerprint=fingerprint(cfg),
                      stages=steps, artifact_state_before=before_state, elapsed_seconds=time.perf_counter() - started,
                      scope='artifact readiness; no full-test quality claim')
        write_json(output.with_name(f'preparation_{time.time_ns()}.json'), report)
        write_json(output, report)
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=['data', 'embeddings', 'indexes', 'recommendation', 'warmup'])
    args = parser.parse_args()
    cfg = runtime_config()
    if args.stage:
        from src.common.seed import set_seed
        set_seed(cfg['seed'])
        stage(cfg, args.stage)
    else:
        prepare(cfg)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
