"""Shared SearchService factory loads one checked bundle during app lifespan."""
from __future__ import annotations

import base64
import copy
import json
from io import BytesIO
import os
from pathlib import Path
from time import perf_counter
from PIL import Image

from src.common.schemas import SearchItem, SearchRequest, SearchResponse
from src.search.searcher import Searcher


class SearchService:
    def __init__(self, searcher: Searcher):
        self.searcher = searcher

    def search(self, request: SearchRequest) -> SearchResponse:
        started = perf_counter(); image = None
        if request.query_image:
            raw = request.query_image.split(',', 1)[1] if request.query_image.startswith('data:') else request.query_image
            with Image.open(BytesIO(base64.b64decode(raw, validate=True))) as source:
                source.load(); image = source.convert('RGB')
        try:
            mode, hits = self.searcher.search(request.query_text, image, request.top_k)
        finally:
            if image is not None:
                image.close()
        results = [SearchItem(product_id=hit.product_id, name=self.searcher.products.loc[hit.product_id, 'name'],
                    score=hit.score, price=float(self.searcher.products.loc[hit.product_id, 'price'])) for hit in hits]
        return SearchResponse(search_type=mode, results=results, latency_ms=(perf_counter()-started)*1000,
                              total_count=len(self.searcher.eligible_ids()))


def create_service(cfg: dict, store=None) -> SearchService | None:
    cfg = copy.deepcopy(cfg)
    # Deployment override also permits explicit missing-model readiness tests.
    if os.getenv('SEARCH_MODEL_DIR'):
        cfg['paths']['model_dir'] = os.environ['SEARCH_MODEL_DIR']
    from src.search.build_embeddings import search_root
    pointer = search_root(cfg)/'indexes_current.json'
    if not pointer.exists():
        return None
    value = json.loads(pointer.read_text())
    if not isinstance(value, dict) or not isinstance(value.get('fingerprint'), str):
        raise ValueError('invalid search model pointer')
    # A present but stale/corrupt bundle fails startup; never silently replace it.
    try:
        return SearchService(Searcher(cfg))
    except FileNotFoundError as error:
        raise ValueError('present search bundle is incomplete') from error
