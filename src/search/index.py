"""Normalized IP search with checked FAISS artifact and product-ID alignment."""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
import faiss
import numpy as np

from src.common.artifacts import file_hash, fingerprint
from src.search.encoder import check_vectors


@dataclass(frozen=True)
class SearchHit:
    product_id: str
    score: float


def configure_faiss(spec: dict) -> None:
    threads = int(spec.get('threads', 4))
    if not 1 <= threads <= 32:
        raise ValueError('FAISS threads must be 1..32')
    faiss.omp_set_num_threads(threads)


def make_index(vectors: np.ndarray, spec: dict, seed: int) -> faiss.Index:
    dim = vectors.shape[1] if vectors.ndim == 2 else 0
    check_vectors(vectors, dim)
    if not len(vectors):
        raise ValueError('cannot index an empty catalog')
    configure_faiss(spec)
    kind = spec['type']
    if spec.get('metric') != 'inner_product':
        raise ValueError('normalized CLIP indexes require explicit inner_product metric')
    if kind == 'HNSW':
        m = int(spec['M']); construction = int(spec['ef_construction']); search = int(spec['ef_search'])
        if m < 2 or construction < m or search < 1:
            raise ValueError('invalid HNSW M/efConstruction/efSearch')
        index = faiss.IndexHNSWFlat(dim, m, faiss.METRIC_INNER_PRODUCT)
        index.hnsw.efConstruction = construction; index.hnsw.efSearch = search
    elif kind == 'IVFPQ':
        nlist, m, nbits = (int(spec[name]) for name in ('nlist', 'm', 'nbits'))
        nprobe = int(spec['nprobe'])
        if nlist < 1 or m < 1 or dim % m or not 1 <= nbits <= 8 or not 1 <= nprobe <= nlist:
            raise ValueError('invalid IVFPQ dimensions/nlist/nbits/nprobe')
        minimum = max(39*nlist, 39*2**nbits)
        training_count = min(len(vectors), int(spec.get('training_samples', len(vectors))))
        if training_count < minimum:
            raise ValueError(f'IVFPQ representative training requires at least {minimum} samples; got {training_count}')
        index = faiss.IndexIVFPQ(faiss.IndexFlatIP(dim), dim, nlist, m, nbits, faiss.METRIC_INNER_PRODUCT)
        index.cp.seed = seed; index.pq.cp.seed = seed
        selected = np.random.default_rng(seed).choice(len(vectors), training_count, replace=False)
        index.train(np.ascontiguousarray(vectors[selected])); index.nprobe = nprobe
    else:
        raise ValueError('configured ANN type must be HNSW or IVFPQ; no silent fallback')
    index.add(np.ascontiguousarray(vectors))
    if index.metric_type != faiss.METRIC_INNER_PRODUCT or index.ntotal != len(vectors):
        raise ValueError('FAISS metric or row count mismatch')
    return index


class SearchIndex:
    def __init__(self, index: faiss.Index, ids: list[str]):
        if index.metric_type != faiss.METRIC_INNER_PRODUCT or index.ntotal != len(ids):
            raise ValueError('index metric/ID count mismatch')
        if len(set(ids)) != len(ids) or any(not isinstance(x, str) for x in ids):
            raise ValueError('unique explicit string IDs required')
        self.index = index; self.ids = ids; self._lock = threading.RLock()

    def search(self, vectors: np.ndarray, k: int) -> list[list[SearchHit]]:
        if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
            raise ValueError('k must be a positive integer')
        check_vectors(vectors, self.index.d)
        with self._lock:
            if hasattr(self.index, 'hnsw'):
                self.index.hnsw.efSearch = max(k, self.index.hnsw.efSearch)
            scores, labels = self.index.search(np.ascontiguousarray(vectors), k)
        output = []
        for row_scores, row_labels in zip(scores, labels):
            row = []
            for score, label in zip(row_scores, row_labels):
                if label == -1:
                    continue
                if not 0 <= label < len(self.ids) or not np.isfinite(score):
                    raise ValueError('FAISS returned invalid label/score')
                row.append(SearchHit(self.ids[int(label)], float(score)))
            output.append(row)
        return output

    @classmethod
    def load(cls, folder: Path, mode: str, embedding_fingerprint: str | None = None) -> 'SearchIndex':
        if mode not in ('text', 'image', 'hybrid'):
            raise ValueError('unknown index modality')
        manifest = json.loads((folder/'manifest.json').read_text())
        if manifest.get('status') != 'COMPLETE' or manifest['fingerprint'] != fingerprint(manifest['identity']):
            raise ValueError('incomplete or corrupt index manifest')
        if embedding_fingerprint and manifest['identity']['embedding_fingerprint'] != embedding_fingerprint:
            raise ValueError('stale index for embedding bundle')
        if set(manifest['files']) != {'item_ids.json', 'text.faiss', 'image.faiss', 'hybrid.faiss'}:
            raise ValueError('incomplete index file manifest')
        for name, digest in manifest['files'].items():
            if Path(name).name != name or file_hash(folder/name) != digest:
                raise ValueError(f'index checksum mismatch: {name}')
        ids = json.loads((folder/'item_ids.json').read_text())
        if fingerprint(ids) != manifest['identity']['ids_fingerprint']:
            raise ValueError('stale or reordered FAISS row mapping')
        configure_faiss(manifest['identity']['faiss'])
        index = faiss.read_index(str(folder/f'{mode}.faiss'))
        kind = manifest['identity']['faiss']['type']
        expected_class = faiss.IndexHNSWFlat if kind == 'HNSW' else faiss.IndexIVFPQ
        if not isinstance(index, expected_class) or index.d != manifest['projection_dim']:
            raise ValueError('serialized FAISS type/dimension differs from manifest')
        return cls(index, ids)
