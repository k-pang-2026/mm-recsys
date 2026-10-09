"""Persist a normalized all-catalog HNSW/IP index with explicit public-ID mapping."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import torch
import numpy as np

from src.common.artifacts import file_hash, write_json
from src.common.config import load_config
from src.recommendation.candidate import ExactCandidate
from src.recommendation.datasets import read_data


def stored_vectors(index) -> np.ndarray:
    """Read HNSWFlat's exact Flat storage, avoiding generic parallel reconstruction."""
    import faiss
    storage = faiss.downcast_index(index.storage)
    if not isinstance(storage, faiss.IndexFlat) or storage.ntotal != index.ntotal or storage.d != index.d:
        raise ValueError('HNSW flat storage mismatch')
    return storage.reconstruct_n(0, storage.ntotal)


def build_index(bundle: Path, model, table, cfg: dict, meta: dict) -> dict:
    from src.recommendation.runtime import configure_inference
    configure_inference(cfg['recommend']['candidate'], with_faiss=True)
    import faiss
    spec = cfg['recommend']['candidate']
    options = spec['faiss']
    if options['type'] != 'HNSW' or options['metric'] != 'inner_product':
        raise ValueError('candidate bundle requires HNSW inner_product')
    rows = np.arange(1, len(table.ids), dtype=np.int64)
    vectors = ExactCandidate(model, table, rows, spec['batch_size']).vectors
    if not np.isfinite(vectors).all() or not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-5):
        raise ValueError('index requires finite unit item vectors')
    # Single-thread construction makes insertion order reproducible. Search uses configured threads.
    faiss.omp_set_num_threads(1)
    index = faiss.IndexHNSWFlat(meta['dim'], int(options['M']), faiss.METRIC_INNER_PRODUCT)
    index.hnsw.efConstruction = int(options.get('ef_construction', 200))
    index.hnsw.efSearch = int(options['ef_search'])
    index.add(np.ascontiguousarray(vectors, dtype=np.float32))
    temporary = bundle / '.item_index.faiss.tmp'
    faiss.write_index(index, str(temporary))
    temporary.replace(bundle / 'item_index.faiss')
    manifest = dict(version='candidate-index-v1', type='HNSWFlat', metric='inner_product', normalized=True,
                    dim=meta['dim'], ntotal=len(rows), mapping='FAISS label i -> item_ids.json[i] -> table row i+1',
                    M=int(options['M']), ef_construction=index.hnsw.efConstruction,
                    ef_search=index.hnsw.efSearch, build_threads=1, faiss_version=faiss.__version__,
                    model_sha256=meta['hashes']['two_tower.pt'], feature_fingerprint=meta['feature_fingerprint'],
                    data_fingerprint=meta['data_fingerprint'], catalog_sha256=meta['catalog_sha256'],
                    config_fingerprint=meta['config_fingerprint'], item_ids_sha256=file_hash(bundle / 'item_ids.json'),
                    vectors_sha256=hashlib.sha256(vectors.tobytes()).hexdigest(),
                    index_sha256=file_hash(bundle / 'item_index.faiss'), catalog_filter='created_at <= request cutoff')
    write_json(bundle / 'index_manifest.json', manifest)
    meta['retrieval'] = 'HNSW inner_product; cutoff filtering and adaptive refill'
    meta['hashes'].update({name: file_hash(bundle / name) for name in ['item_index.faiss', 'index_manifest.json']})
    meta['contract']['files'].update({'item_index.faiss': 'all catalog normalized HNSW/IP, labels aligned to item_ids.json',
                                    'index_manifest.json': 'index parameters and model/data/config/mapping checksums'})
    meta['contract'].pop('planned_B3b', None)
    write_json(bundle / 'meta.json', meta)
    configure_inference(spec, with_faiss=True)
    return manifest


def load_index(bundle: Path, table, meta: dict):
    from src.recommendation.runtime import configure_inference
    configure_inference(meta['training_spec'], with_faiss=True)
    import faiss
    manifest = json.loads((bundle / 'index_manifest.json').read_text())
    for key in ['data_fingerprint', 'catalog_sha256', 'config_fingerprint', 'feature_fingerprint']:
        if manifest[key] != meta[key]:
            raise ValueError(f'stale index {key}')
    checks = {'item_index.faiss': manifest['index_sha256'], 'item_ids.json': manifest['item_ids_sha256'],
              'two_tower.pt': manifest['model_sha256']}
    for name, digest in checks.items():
        if file_hash(bundle / name) != digest or meta['hashes'].get(name) != digest:
            raise ValueError(f'index checksum mismatch: {name}')
    if file_hash(bundle / 'index_manifest.json') != meta['hashes'].get('index_manifest.json'):
        raise ValueError('index manifest checksum mismatch')
    if json.loads((bundle / 'item_ids.json').read_text()) != table.ids[1:]:
        raise ValueError('index ID mapping mismatch')
    index = faiss.read_index(str(bundle / 'item_index.faiss'))
    if (not isinstance(index, faiss.IndexHNSWFlat) or index.metric_type != faiss.METRIC_INNER_PRODUCT
            or index.d != meta['dim'] or index.ntotal != len(table.ids) - 1
            or manifest['ntotal'] != index.ntotal or manifest['dim'] != index.d):
        raise ValueError('index shape/type/metric mismatch')
    if (manifest['type'] != 'HNSWFlat' or manifest['metric'] != 'inner_product' or not manifest['normalized']
            or index.hnsw.nb_neighbors(0) != 2 * manifest['M']
            or index.hnsw.efConstruction != manifest['ef_construction']):
        raise ValueError('index manifest parameters mismatch')
    vectors = stored_vectors(index)
    if hashlib.sha256(vectors.tobytes()).hexdigest() != manifest['vectors_sha256']:
        raise ValueError('index vector checksum mismatch')
    index.hnsw.efSearch = int(manifest['ef_search'])
    return index, manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', type=Path)
    args = parser.parse_args()
    cfg = load_config()
    import torch
    from src.recommendation.runtime import configure_inference
    configure_inference(cfg['recommend']['candidate'])
    from src.recommendation.train_two_tower import load_bundle
    bundle = args.bundle or Path(cfg['paths']['model_dir']) / 'v1.0'
    data = read_data(cfg['paths']['data_dir'], 'valid')
    model, _, table, meta = load_bundle(bundle, data, cfg)
    manifest = build_index(bundle, model, table, cfg, meta)
    print(f"index: {manifest['ntotal']} items; {manifest['index_sha256']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
