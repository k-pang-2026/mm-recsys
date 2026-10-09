"""Publish text/image/hybrid HNSW or IVFPQ indexes as an atomic versioned bundle."""
from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
import faiss
import numpy as np

from src.common.artifacts import file_hash, fingerprint, write_json
from src.common.config import load_config
from src.common.seed import set_seed
from src.search.build_embeddings import current_bundle, search_root
from src.search.encoder import unit_vectors
from src.search.index import make_index, SearchIndex


def fuse(text, image, weights: dict):
    a = float(weights['text_weight']); b = float(weights['image_weight'])
    if not 0 <= a <= 1 or not 0 <= b <= 1 or a+b <= 0:
        raise ValueError('fusion weights must be finite, nonnegative and not both zero')
    if text.shape != image.shape:
        raise ValueError('fusion requires aligned projected modalities')
    return unit_vectors(a*text + b*image, text.shape[1])


def build_indexes(cfg: dict) -> Path:
    bundle = current_bundle(cfg); embeddings = bundle['manifest']
    identity = {'version': 1, 'embedding_fingerprint': embeddings['fingerprint'],
                'ids_fingerprint': fingerprint(bundle['ids']), 'faiss': cfg['search']['faiss'],
                'fusion': cfg['search']['fusion'], 'seed': cfg['seed'], 'faiss_version': faiss.__version__,
                'deduplicate_vectors': cfg['search'].get('deduplicate_vectors', False)}
    key = fingerprint(identity); base = search_root(cfg)/'indexes'; base.mkdir(parents=True, exist_ok=True)
    target = base/key
    if target.exists():
        for mode in ('text', 'image', 'hybrid'):
            SearchIndex.load(target, mode, embeddings['fingerprint'])
        write_json(search_root(cfg)/'indexes_current.json', {'fingerprint': key})
        return target
    staging = Path(tempfile.mkdtemp(prefix=f'.{key}.', dir=base))
    try:
        vectors = {'text': bundle['text'], 'image': bundle['image'],
                   'hybrid': fuse(bundle['text'], bundle['image'], cfg['search']['fusion'])}
        for mode, values in vectors.items():
            if identity['deduplicate_vectors']:
                lookup = {}; members = []; first = []
                for position, vector in enumerate(values):
                    content = vector.tobytes()
                    if content not in lookup:
                        lookup[content] = len(members); members.append([]); first.append(position)
                    members[lookup[content]].append(position)
                indexed = np.ascontiguousarray(values[first])
                write_json(staging/f'{mode}_members.json', members)
            else:
                indexed = values
            index = make_index(indexed, cfg['search']['faiss'], cfg['seed'])
            faiss.write_index(index, str(staging/f'{mode}.faiss'))
            print(f'{mode}: {index.ntotal} indexed vectors, IP {cfg["search"]["faiss"]["type"]}', flush=True)
        write_json(staging/'item_ids.json', bundle['ids'])
        names = ['item_ids.json', *[f'{mode}.faiss' for mode in vectors]]
        if identity['deduplicate_vectors']:
            names.extend(f'{mode}_members.json' for mode in vectors)
        write_json(staging/'manifest.json', {'status': 'COMPLETE', 'fingerprint': key, 'identity': identity,
                   'count': len(bundle['ids']), 'projection_dim': vectors['text'].shape[1],
                   'files': {name: file_hash(staging/name) for name in names}})
        for mode in vectors:
            SearchIndex.load(staging, mode, embeddings['fingerprint'])
        staging.rename(target)
        write_json(search_root(cfg)/'indexes_current.json', {'fingerprint': key})
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return target


def current_indexes(cfg: dict) -> tuple[Path, dict]:
    bundle = current_bundle(cfg); base = search_root(cfg)
    key = json.loads((base/'indexes_current.json').read_text())['fingerprint']
    if not isinstance(key, str) or len(key) != 64 or any(x not in '0123456789abcdef' for x in key):
        raise ValueError('invalid index pointer')
    folder = base/'indexes'/key
    manifest = json.loads((folder/'manifest.json').read_text())
    if manifest['fingerprint'] != key:
        raise ValueError('index pointer/version mismatch')
    identity = manifest['identity']
    if (identity['embedding_fingerprint'] != bundle['manifest']['fingerprint'] or
            identity['faiss'] != cfg['search']['faiss'] or identity['fusion'] != cfg['search']['fusion'] or
            identity['seed'] != cfg['seed'] or
            identity.get('deduplicate_vectors', False) != cfg['search'].get('deduplicate_vectors', False)):
        raise ValueError('stale index configuration/embedding version')
    return folder, bundle


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__); parser.parse_args()
    cfg = load_config(); set_seed(cfg['seed'])
    print('INDEXES VERIFIED:', build_indexes(cfg))


if __name__ == '__main__':
    main()
