"""Read the deployed catalog and actual CLIP bundle without loading ML frameworks."""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path

import numpy as np
import pandas as pd

from dashboard.data import ab_record
from src.common.artifacts import file_hash, fingerprint
from src.recommendation.bundle_compat import training_config_matches


def deployment(results: Path) -> dict | None:
    path = results / 'deployment.json'
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding='utf-8'))
    manifest = json.loads((Path(value['data_dir']) / 'split_manifest.json').read_text())
    if manifest['generation_fingerprint'] != value['data_fingerprint']:
        raise ValueError('배포 데이터 identity가 manifest와 다릅니다. 준비 단계를 다시 확인하세요.')
    return value


def different_recommendation_policy(report: dict, results: Path) -> bool:
    path = results / 'deployment.json'
    if not path.is_file():
        return False
    active = json.loads(path.read_text(encoding='utf-8')).get('recommendation_policy_sources', {})
    measured = report.get('identity', {}).get('source_hashes', {})
    return any(measured.get(name) != digest for name, digest in active.items())


def reference_identity(report: dict, results: Path) -> str:
    active = deployment(results)
    if active is None:
        return '현재 배포의 데이터·모델을 준비하면 최종 제출 기록과 비교합니다.'
    if (active['data_fingerprint'] != report['data_fingerprint']
            or file_hash(Path(active['data_dir']) / 'split_manifest.json') != report['identity']['data_manifest_sha256']):
        return '현재 배포는 최종 제출 기록과 다른 데이터를 사용합니다.'
    model = Path(active['model_dir'])
    registry = json.loads((model / 'registry.json').read_text())
    if registry['active'] != report['model_version']:
        return '현재 활성 모델 버전이 최종 제출 기록과 다릅니다.'
    for kind, subdir in (('candidate', ''), ('ranking', 'ranking'), ('session', 'session')):
        folder = model / registry['active'] / subdir
        hashes = json.loads((folder / 'meta.json').read_text())['hashes']
        expected = report['recommendation']['models'][kind]['hashes']
        if hashes == expected:
            continue
        # Legacy releases recorded the implicit gradient clipping default differently.
        # Accept a manifest-only difference after checking the complete index and recipe.
        changed = {key for key in hashes.keys() | expected.keys() if hashes.get(key) != expected.get(key)}
        if kind == 'candidate' and changed == {'index_manifest.json'}:
            path = folder / 'index_manifest.json'
            measured_index = dict(report['recommendation']['models']['index'])
            active_index = json.loads(path.read_text())
            recipe = registry['versions'][registry['active']]['config']['recommend']
            if (file_hash(path) == hashes['index_manifest.json']
                    and training_config_matches(measured_index.pop('config_fingerprint'), recipe)
                    and training_config_matches(active_index.pop('config_fingerprint'), recipe)
                    and active_index == measured_index):
                continue
        return '데이터는 일치하며 추천 모델 산출물은 최종 제출 기록과 다릅니다.'
    search = model / active['search_subdir']
    for key, directory in (('embeddings', 'embeddings'), ('index', 'indexes')):
        pointer = json.loads((search / f'{directory}_current.json').read_text())
        expected_bundle = report['search']['models'][key]
        if pointer['fingerprint'] != expected_bundle['fingerprint']:
            return '데이터와 추천 모델은 일치하며 검색 번들은 최종 제출 기록과 다릅니다.'
        if not expected_bundle.get('files'):
            return '최종 제출 기록에 검색 파일 해시가 없어 산출물 일치 여부를 확인할 수 없습니다.'
        manifest = json.loads((search / directory / pointer['fingerprint'] / 'manifest.json').read_text())
        if manifest.get('files') != expected_bundle['files']:
            return '데이터·검색 설정·추천 모델은 일치하며 검색 파일 해시는 최종 제출 기록과 다릅니다.'
    return '현재 배포와 최종 제출 기록의 데이터·검색 번들·추천 모델이 일치합니다.'


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


def _initial_models_match(model_dir: str, bundles: dict) -> bool:
    root = Path(model_dir) / 'v1.0'
    return all(json.loads((root / subdir / 'meta.json').read_text())['hashes'] == bundles[kind]['hashes']
               for kind, subdir in [('candidate', ''), ('ranking', 'ranking'), ('session', 'session')])


def ab_result(results: Path) -> dict | None:
    active = deployment(results)
    if active is None:
        return None
    policy = active.get('recommendation_policy_sources', {})
    measured = results / 'evaluation_full_test.json'
    if measured.is_file():
        report = json.loads(measured.read_text(encoding='utf-8'))
        ab = report.get('ab', {})
        if (ab.get('status') == 'MEASURED' and report.get('data_fingerprint') == active['data_fingerprint']
                and policy and not different_recommendation_policy(report, results)
                and _initial_models_match(active['model_dir'], report['recommendation']['models'])):
            return dict(ab, source=str(measured))
    path = results / 'ab_test.json'
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding='utf-8'))
    if value['status'] != 'PASS' or value['identity']['data_fingerprint'] != active['data_fingerprint']:
        raise ValueError('A/B와 배포 데이터 identity가 다릅니다.')
    if any(value['identity'].get('source_hashes', {}).get(name) != digest for name, digest in policy.items()):
        return None
    if not _initial_models_match(active['model_dir'], value['identity']['bundle_metadata']):
        raise ValueError('A/B와 배포 초기 모델이 다릅니다.')
    return ab_record(value, path)
