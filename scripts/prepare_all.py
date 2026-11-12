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

from src.common.console import log, emit_json, run_cli
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
        log('모델', '준비', '고정 CLIP 다운로드 캐시 재사용 (오프라인)', status='성공')
        return
    except LocalEntryNotFoundError:
        pass
    log('모델', '다운로드', f"CLIP={spec['clip_model']} / revision={spec['clip_revision']}")
    snapshot_download(spec['clip_model'], revision=spec['clip_revision'],
                      allow_patterns=['*.json', '*.txt', 'pytorch_model.bin', '*.safetensors'])


def stage(cfg: dict, name: str) -> None:
    if name == 'data':
        from src.simulator.generate import generate
        generate(cfg)
    elif name == 'audit':
        from src.evaluation.data_audit import audit
        audit(cfg)
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
            log('모델', '준비', f'FAISS {mode}: 벡터={index.ntotal:,}개 / 차원={index.d}', status='성공')
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
            log('모델', '준비', '호환되는 추천 모델 재사용 완료', status='성공')
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
            result = warmup(cfg, store)
            log('Redis', '준비', f'사용자 프로필 적재 완료 / 결과={result}', status='성공')
        finally:
            store.close()
        if cfg['serving']['ct']['enabled']:
            state = bootstrap(cfg)
            from src.ct.retrain_trigger import components
            from src.serving.model_loader import load_record
            from src.serving.memory_store import MemoryFeatureStore
            _, _, registry = components(cfg)
            record = registry.verify(state['active'])
            from src.recommendation.bundle_compat import legacy_training_spec
            if ({k:v for k,v in legacy_training_spec(record['config']['recommend']).items() if k!='scoring'}
                    != {k:v for k,v in legacy_training_spec(cfg['recommend']).items() if k!='scoring'}):
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
        labels = dict(data='데이터', audit='데이터 분석', embeddings='검색 임베딩', indexes='FAISS 인덱스',
                      recommendation='추천 모델', warmup='Redis 사용자 프로필')
        log('서버', '준비', f'{cfg["scale"]} 환경 / 상품 {cfg["simulator"]["n_products"]:,}개 / 호환 산출물 검사 후 필요한 생성·학습 시작')
        for name in ('data', 'audit', 'embeddings', 'indexes', 'recommendation', 'warmup'):
            before = time.perf_counter()
            command = [sys.executable, str(Path(__file__).resolve()), '--stage', name]
            log(labels[name], '준비', '시작')
            detail = output.parent / 'logs' / f'prepare-{name}-{time.time_ns()}.log'
            detail.parent.mkdir(parents=True, exist_ok=True)
            with detail.open('w', encoding='utf-8') as stream:
                result = subprocess.run(command, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                        timeout=float(os.getenv('PREPARE_TIMEOUT_SECONDS', '21600')))
            steps.append(dict(stage=name, command=command, exit_code=result.returncode,
                              seconds=time.perf_counter() - before, log=str(detail)))
            if result.returncode:
                sys.stderr.write(detail.read_text(encoding='utf-8'))
                log(labels[name], '준비', f'자식 프로세스 종료 코드={result.returncode} / 다음 조치: 위 원본 오류와 해당 단계의 입력·설정을 확인한 뒤 재실행하세요.', status='실패')
                write_json(output, dict(status='FAIL', scale=cfg['scale'], stages=steps))
                raise RuntimeError(f'preparation failed at {name}: exit {result.returncode}')
            log(labels[name], '준비', f'완료 / 소요 시간={steps[-1]["seconds"]:.1f}초', status='성공')
        manifest = Path(cfg['paths']['data_dir']) / 'split_manifest.json'
        report = dict(status='PASS', acceptance='UNMEASURED', scale=cfg['scale'],
                      data_fingerprint=json.loads(manifest.read_text())['generation_fingerprint'],
                      manifest_sha256=file_hash(manifest), config_fingerprint=fingerprint(cfg),
                      stages=steps, artifact_state_before=before_state, elapsed_seconds=time.perf_counter() - started,
                      scope='artifact readiness; no full-test quality claim')
        write_json(output.with_name(f'preparation_{time.time_ns()}.json'), report)
        write_json(output, report)
        write_json(output.with_name('deployment.json'), dict(data_dir=cfg['paths']['data_dir'],
            model_dir=cfg['paths']['model_dir'], search_subdir=cfg['search']['artifact_subdir'],
            data_fingerprint=report['data_fingerprint']))
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=['data', 'audit', 'embeddings', 'indexes', 'recommendation', 'warmup'])
    args = parser.parse_args()
    cfg = runtime_config()
    if args.stage:
        from src.common.seed import set_seed
        set_seed(cfg['seed'])
        stage(cfg, args.stage)
    else:
        report = prepare(cfg)
        if os.getenv('MM_LOG_FORMAT') != 'compact':
            emit_json(report)
    return 0


if __name__ == '__main__':
    raise SystemExit(run_cli(main, '환경 준비', '위 단계의 원본 오류, 저장 공간·데이터 fingerprint·모델 경로·Redis 연결을 확인하세요. 기존 산출물은 보존하세요.'))
