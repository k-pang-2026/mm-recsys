"""Local CLIP retrieval; no evaluation labels or frozen-query lookup are accepted."""
from __future__ import annotations

from pathlib import Path
import threading
import numpy as np
import pandas as pd

from src.search.build_index import current_indexes, fuse
from src.search.encoder import CLIPEncoder
from src.search.index import SearchIndex


class Searcher:
    def __init__(self, cfg: dict, encoder=None):
        self.cfg = cfg; self._lock = threading.RLock()
        folder, self.bundle = current_indexes(cfg)
        self.encoder = encoder or CLIPEncoder(cfg)
        self.indexes = {mode: SearchIndex.load(folder, mode, self.bundle['manifest']['fingerprint'])
                        for mode in ('text', 'image', 'hybrid')}
        self.products = pd.read_parquet(Path(cfg['paths']['data_dir'])/'products.parquet').set_index('product_id')
        self.created = pd.to_datetime(self.products.created_at, utc=True)
        self._eligible_cache = {}

    def eligible_ids(self, cutoff=None) -> set[str]:
        key = str(cutoff or self.cfg['simulator']['reference_time'])
        if key not in self._eligible_cache:
            self._eligible_cache[key] = set(self.products.index[self.created <= pd.Timestamp(key)])
        return self._eligible_cache[key]

    def encode(self, query_text=None, query_image=None):
        has_text = isinstance(query_text, str) and bool(query_text.strip())
        if not has_text and query_image is None:
            raise ValueError('query_text or query_image is required')
        mode = 'hybrid' if has_text and query_image is not None else 'text' if has_text else 'image'
        with self._lock:
            text = self.encoder.encode_texts([query_text]) if has_text else None
            image = self.encoder.encode_images([query_image]) if query_image is not None else None
        query = fuse(text, image, self.cfg['search']['query_fusion']) if mode == 'hybrid' else text if has_text else image
        return mode, query

    def retrieve(self, mode: str, query: np.ndarray, k: int, cutoff=None):
        index_mode = self.cfg['search']['modes'][mode]
        return self.indexes[index_mode].search(query, k, self.eligible_ids(cutoff))[0]

    def search(self, query_text=None, query_image=None, k=10, cutoff=None):
        mode, vectors = self.encode(query_text, query_image)
        return mode, self.retrieve(mode, vectors, k, cutoff)
