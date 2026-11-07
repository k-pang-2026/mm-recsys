"""Read the deployed catalog and actual CLIP bundle without loading ML frameworks."""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.common.artifacts import file_hash, fingerprint


def deployment(results: Path) -> dict | None:
    path = results / 'deployment.json'
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding='utf-8'))
    manifest = json.loads((Path(value['data_dir']) / 'split_manifest.json').read_text())
    if manifest['generation_fingerprint'] != value['data_fingerprint']:
        raise ValueError('배포 데이터 identity가 manifest와 다릅니다. 준비 단계를 다시 확인하세요.')
    return value


@lru_cache(maxsize=2)
def catalog(data_dir: str, identity: str) -> pd.DataFrame:
    root = Path(data_dir)
    manifest = json.loads((root / 'split_manifest.json').read_text())
    if manifest['generation_fingerprint'] != identity or file_hash(root / 'products.parquet') != manifest['file_hashes']['products.parquet']:
        raise ValueError('상품 데이터 checksum 또는 fingerprint 불일치')
    return pd.read_parquet(root / 'products.parquet').set_index('product_id', drop=False)


@lru_cache(maxsize=2)
def clip_bundle(model_dir: str, subdir: str, data_dir: str, identity: str, pointer: str) -> dict:
    root = Path(model_dir) / subdir
    if len(pointer) != 64 or any(c not in '0123456789abcdef' for c in pointer):
        raise ValueError('잘못된 CLIP bundle pointer')
    folder = root / 'embeddings' / pointer
    manifest = json.loads((folder / 'manifest.json').read_text())
    if (manifest['status'] != 'COMPLETE' or manifest['fingerprint'] != pointer
            or fingerprint(manifest['identity']) != pointer
            or manifest['identity']['data_fingerprint'] != identity
            or manifest['identity']['catalog_sha256'] != file_hash(Path(data_dir) / 'products.parquet')):
        raise ValueError('현재 배포와 CLIP 번들 identity가 다릅니다.')
    for name, digest in manifest['files'].items():
        if Path(name).name != name or file_hash(folder / name) != digest:
            raise ValueError(f'CLIP 파일 checksum 불일치: {name}')
    ids = json.loads((folder / 'item_ids.json').read_text())
    if len(ids) != manifest['count'] or fingerprint(ids) != manifest['identity']['ids_fingerprint']:
        raise ValueError('CLIP ID mapping 불일치')
    return dict(manifest=manifest, ids=ids, positions={pid: i for i,pid in enumerate(ids)},
        texts=json.loads((folder / 'text_audit.json').read_text()),
        vectors={mode: np.load(folder / f'{mode}.npy', mmap_mode='r', allow_pickle=False) for mode in ('text', 'image')})


def clip_item(deployed: dict, product_id: str) -> dict:
    pointer = json.loads((Path(deployed['model_dir']) / deployed['search_subdir'] / 'embeddings_current.json').read_text())['fingerprint']
    bundle = clip_bundle(deployed['model_dir'], deployed['search_subdir'], deployed['data_dir'], deployed['data_fingerprint'], pointer)
    index = bundle['positions'][product_id]
    vectors = {}
    for mode, values in bundle['vectors'].items():
        if values.shape != (len(bundle['ids']), bundle['manifest']['identity']['encoder']['projection_dim']):
            raise ValueError('CLIP 벡터와 ID 크기 불일치')
        vector = values[index]
        norm = float(np.linalg.norm(vector))
        if not np.isfinite(vector).all() or not np.isclose(norm, 1, atol=1e-5):
            raise ValueError('CLIP 벡터 유효성 검사 실패')
        vectors[mode] = dict(dimension=len(vector), norm=norm, first_12_values=vector[:12].tolist())
    return dict(product_id=product_id, item_ids_index=index, text=bundle['texts'][index],
        encoder=bundle['manifest']['identity']['encoder'], vectors=vectors,
        bundle_fingerprint=bundle['manifest']['fingerprint'], data_fingerprint=deployed['data_fingerprint'])


def image_path(deployed: dict, row: pd.Series) -> Path:
    root = Path(deployed['data_dir']).resolve()
    path = (root / row['image_path']).resolve()
    if not path.is_relative_to(root):
        raise ValueError('상품 이미지가 데이터 경로를 벗어났습니다.')
    return path


def ab_result(results: Path) -> dict | None:
    active = deployment(results)
    path = results / 'ab_test.json'
    if active is None or not path.exists():
        return None
    value = json.loads(path.read_text(encoding='utf-8'))
    if value['status'] != 'PASS' or value['identity']['data_fingerprint'] != active['data_fingerprint']:
        raise ValueError('A/B와 배포 데이터 identity가 다릅니다.')
    for kind, subdir in [('candidate', ''), ('ranking', 'ranking'), ('session', 'session')]:
        folder = Path(active['model_dir']) / 'v1.0' / subdir
        meta = json.loads((folder / 'meta.json').read_text())
        if meta['hashes'] != value['identity']['bundle_metadata'][kind]['hashes']:
            raise ValueError('A/B와 배포 초기 모델이 다릅니다.')
    return dict(status='MEASURED', source=str(path), days=value['days'], seed=value['seed'],
        strategies=value['strategies'], denominators=value['denominators'], inference=value['inference'],
        arms={key: {k: v for k,v in row.items() if k != 'arm_statistics'} for key,row in value['arms'].items()},
        limitations=value['limitations'])
