"""Content-deduplicated, checked chunk resume and atomic embedding publication."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import numpy as np
import pandas as pd

from src.common.artifacts import file_hash, fingerprint, write_json
from src.common.config import load_config
from src.common.seed import set_seed
from src.search.encoder import CLIPEncoder, check_vectors
from src.search.text import normalize_text
from src.search.locking import writer_lock


def search_root(cfg: dict) -> Path:
    subdir = Path(cfg['search'].get('artifact_subdir', 'search'))
    if subdir.is_absolute() or '..' in subdir.parts:
        raise ValueError('artifact_subdir must stay within model_dir')
    return Path(cfg['paths']['model_dir']) / subdir


def atomic_array(path: Path, vectors: np.ndarray) -> None:
    temporary = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    with temporary.open('wb') as stream:
        np.save(stream, vectors, allow_pickle=False)
    temporary.replace(path)


def load_bundle(folder: Path, expected: dict | None = None) -> dict:
    manifest = json.loads((folder / 'manifest.json').read_text())
    if manifest.get('status') != 'COMPLETE':
        raise ValueError('incomplete embedding bundle')
    if expected is not None and manifest['identity'] != expected:
        raise ValueError('incompatible catalog/model/preprocessing manifest')
    if manifest['fingerprint'] != fingerprint(manifest['identity']):
        raise ValueError('invalid embedding identity fingerprint')
    if set(manifest['files']) != {'text.npy', 'image.npy', 'item_ids.json', 'text_audit.json'}:
        raise ValueError('incomplete embedding file manifest')
    for name, digest in manifest['files'].items():
        if Path(name).name != name or file_hash(folder/name) != digest:
            raise ValueError(f'embedding checksum mismatch: {name}')
    ids = json.loads((folder/'item_ids.json').read_text())
    if len(ids) != manifest['count'] or len(set(ids)) != len(ids) or any(not isinstance(x, str) for x in ids):
        raise ValueError('invalid aligned product IDs')
    if fingerprint(ids) != manifest['identity']['ids_fingerprint']:
        raise ValueError('embedding ID order differs from identity')
    vectors = {mode: np.load(folder/f'{mode}.npy', mmap_mode='r', allow_pickle=False) for mode in ('text', 'image')}
    for value in vectors.values():
        check_vectors(value, manifest['identity']['encoder']['projection_dim'], len(ids))
    return {'manifest': manifest, 'ids': ids, **vectors, 'folder': folder}


def _chunks(folder: Path, mode: str, keys: list[str], values: list, encoder, chunk_size: int) -> np.ndarray:
    chunks = folder / 'chunks'; chunks.mkdir(exist_ok=True)
    output = []
    method = encoder.encode_texts if mode == 'text' else encoder.encode_images
    for start in range(0, len(keys), chunk_size):
        batch_keys = keys[start:start+chunk_size]
        path = chunks / f'{mode}-{start:09d}.npy'
        receipt = path.with_suffix('.json')
        if receipt.exists():
            record = json.loads(receipt.read_text())
            if record['keys'] != batch_keys or file_hash(path) != record['sha256']:
                raise ValueError(f'corrupt or incompatible completed chunk: {path}')
            vectors = np.load(path, allow_pickle=False)
        else:
            # A crashed write without its completion receipt is never treated as complete.
            vectors = method(values[start:start+chunk_size])
            check_vectors(vectors, encoder.dim, len(batch_keys))
            atomic_array(path, vectors)
            write_json(receipt, {'keys': batch_keys, 'sha256': file_hash(path)})
        check_vectors(vectors, encoder.dim, len(batch_keys))
        output.append(vectors)
        print(f'{mode}: unique {min(start+chunk_size, len(keys))}/{len(keys)}', flush=True)
    return np.concatenate(output)


def build_embeddings(cfg: dict, encoder=None) -> Path:
    data = Path(cfg['paths']['data_dir']); catalog = data/'products.parquet'
    split = json.loads((data/'split_manifest.json').read_text())
    catalog_hash = file_hash(catalog)
    if split['file_hashes']['products.parquet'] != catalog_hash:
        raise ValueError('catalog differs from frozen dataset manifest')
    products = pd.read_parquet(catalog).sort_values('product_id', kind='stable').reset_index(drop=True)
    ids = products.product_id.tolist()
    if not ids or len(set(ids)) != len(ids) or any(not isinstance(x, str) for x in ids):
        raise ValueError('catalog needs unique string product IDs')
    records = [normalize_text(text).to_dict() for text in products.description_en]
    texts = [record['encoded'] for record in records]
    image_keys = []; image_paths = []
    for row in products.itertuples():
        path = data / row.image_path
        if not path.resolve().is_relative_to(data.resolve()):
            raise ValueError('image path escapes data_dir')
        digest = file_hash(path)
        if digest != row.image_sha256:
            raise ValueError(f'catalog image checksum mismatch: {row.product_id}')
        image_keys.append(digest); image_paths.append(path)
    encoder = encoder or CLIPEncoder(cfg)
    identity = {'version': 1, 'scale': cfg['scale'], 'data_fingerprint': split['generation_fingerprint'],
                'catalog_sha256': catalog_hash, 'ids_fingerprint': fingerprint(ids),
                'text_content_fingerprint': fingerprint(texts), 'image_content_fingerprint': fingerprint(image_keys),
                'encoder': encoder.metadata}
    key = fingerprint(identity); base = search_root(cfg)/'embeddings'; base.mkdir(parents=True, exist_ok=True)
    target = base/key
    with writer_lock(base/'.locks'/f'{key}.lock'):
        if target.exists():
            load_bundle(target, identity)
            write_json(search_root(cfg)/'embeddings_current.json', {'fingerprint': key})
            return target
        staging = base/f'.{key}.partial'; staging.mkdir(exist_ok=True)
        progress = staging/'identity.json'
        if progress.exists() and json.loads(progress.read_text()) != identity:
            raise ValueError('incompatible resume identity')
        write_json(progress, identity)
        chunk_size = int(cfg['search'].get('embedding_chunk_size', 256))
        if chunk_size <= 0:
            raise ValueError('embedding_chunk_size must be positive')
        stats = {}
        for mode, content_keys, values in [('text', texts, texts), ('image', image_keys, image_paths)]:
            first = {}; positions = []
            for i, content in enumerate(content_keys):
                if content not in first:
                    first[content] = i
                positions.append(content)
            unique_keys = list(first)
            unique_values = [values[first[value]] for value in unique_keys]
            vectors = _chunks(staging, mode, unique_keys, unique_values, encoder, chunk_size)
            lookup = {value: i for i, value in enumerate(unique_keys)}
            aligned = vectors[[lookup[value] for value in positions]]
            check_vectors(aligned, encoder.dim, len(ids)); atomic_array(staging/f'{mode}.npy', aligned)
            stats[mode] = {'unique_contents': len(unique_keys), 'cache_hits': len(ids)-len(unique_keys)}
        write_json(staging/'item_ids.json', ids)
        write_json(staging/'text_audit.json', [dict(product_id=id_, **record) for id_, record in zip(ids, records)])
        names = ['text.npy', 'image.npy', 'item_ids.json', 'text_audit.json']
        manifest = {'status': 'COMPLETE', 'fingerprint': key, 'identity': identity, 'count': len(ids),
                    'content_cache': stats, 'files': {name: file_hash(staging/name) for name in names}}
        write_json(staging/'manifest.json', manifest)
        load_bundle(staging, identity)
        staging.rename(target)
        write_json(search_root(cfg)/'embeddings_current.json', {'fingerprint': key})
    return target


def current_bundle(cfg: dict) -> dict:
    base = search_root(cfg)
    key = json.loads((base/'embeddings_current.json').read_text())['fingerprint']
    if not isinstance(key, str) or len(key) != 64 or any(x not in '0123456789abcdef' for x in key):
        raise ValueError('invalid embedding pointer')
    bundle = load_bundle(base/'embeddings'/key)
    if bundle['manifest']['fingerprint'] != key:
        raise ValueError('embedding pointer/version mismatch')
    identity = bundle['manifest']['identity']
    data = Path(cfg['paths']['data_dir'])
    if identity['scale'] != cfg['scale'] or identity['catalog_sha256'] != file_hash(data/'products.parquet'):
        raise ValueError('stale embeddings for current catalog/scale')
    split = json.loads((data/'split_manifest.json').read_text())
    if identity['data_fingerprint'] != split['generation_fingerprint']:
        raise ValueError('stale dataset fingerprint')
    search = cfg['search']
    if identity['encoder']['model'] != search['clip_model'] or identity['encoder']['model_revision'] != search['clip_revision']:
        raise ValueError('stale embeddings for configured CLIP model')
    from src.search.text import ALIASES, PREPROCESS_VERSION
    if (identity['encoder']['preprocess_version'] != PREPROCESS_VERSION or
            identity['encoder']['alias_fingerprint'] != fingerprint(ALIASES)):
        raise ValueError('stale embeddings for text preprocessing')
    return bundle


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__); parser.parse_args()
    cfg = load_config(); set_seed(cfg['seed'])
    print('EMBEDDINGS VERIFIED:', build_embeddings(cfg))


if __name__ == '__main__':
    main()
