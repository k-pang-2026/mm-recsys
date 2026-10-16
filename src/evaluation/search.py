"""B8 search measurement without rewriting A's frozen reports or settings."""
from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter

import numpy as np
import pandas as pd

from src.common.artifacts import file_hash, fingerprint
from src.evaluation.reporting import relative_lift
from src.search.bm25 import BM25Search
from src.search.build_index import current_indexes, fuse
from src.search.eval_search import encoded_queries, score_rankings
from src.search.eval_support import relevant_ids, ann_agreement
from src.search.queries import freeze_queries
from src.search.searcher import Searcher


def evaluate(cfg: dict, split: str) -> dict:
    folder = freeze_queries(cfg)
    query_manifest = json.loads((folder / 'manifest.json').read_text())
    searcher = Searcher(cfg)
    queries, vectors = encoded_queries(searcher, folder, split)
    # Pinned macOS ARM torch/FAISS wheels load different OpenMP runtimes.
    # Reuse B's established inference policy after A's index loader sets threads.
    from src.recommendation.runtime import configure_inference
    threads = configure_inference(cfg['recommend']['candidate'], with_faiss=True)
    cutoff = pd.Timestamp(query_manifest['identity']['cutoffs'][split])
    eligible = searcher.eligible_ids(cutoff)
    products = searcher.products.reset_index()
    truth = [relevant_ids(products, q['relevance_attributes'], q['mode'], cutoff) for q in queries]
    audit = json.loads((searcher.bundle['folder'] / 'text_audit.json').read_text())
    bm25 = BM25Search(searcher.bundle['ids'], [q['raw'] for q in audit])
    all_ranked: list[list[str]] = [[] for _ in queries]
    per_mode, baselines, tradeoff = {}, {}, []
    for mode in ('text', 'image', 'hybrid'):
        print(f'B8 search {split}: {mode}', flush=True)
        active = [i for i, query in enumerate(queries) if query['mode'] == mode]
        labels = [truth[i] for i in active]
        query_vectors = (fuse(vectors['text'][active], vectors['image'][active], cfg['search']['query_fusion'])
                         if mode == 'hybrid' else vectors[mode][active])
        gallery = cfg['search']['modes'][mode]
        search = searcher.indexes[gallery]
        hits = search.search(query_vectors, 10, eligible)
        ranked = [[hit.product_id for hit in row] for row in hits]
        per_mode[mode] = dict(gallery=gallery, **score_rankings(ranked, labels))
        for i, ids in zip(active, ranked):
            all_ranked[i] = ids
        source = (fuse(searcher.bundle['text'], searcher.bundle['image'], cfg['search']['fusion'])
                  if gallery == 'hybrid' else searcher.bundle[gallery])
        positions = [i for i, pid in enumerate(searcher.bundle['ids']) if pid in eligible]
        lookup = {searcher.bundle['ids'][pos]: i for i, pos in enumerate(positions)}
        per_mode[mode]['ann_vs_exact'] = ann_agreement(source[positions], query_vectors,
            np.array([[hit.score for hit in row] for row in hits], dtype=np.float32),
            np.array([[lookup[hit.product_id] for hit in row] for row in hits]), 10)
        if mode != 'image':
            baseline = [[hit.product_id for hit in bm25.search(queries[i]['query_text'], 10, eligible)] for i in active]
            baselines[mode] = score_rankings(baseline, labels)
            per_mode[mode]['bm25_relative_lift'] = {name: relative_lift(per_mode[mode][name], baselines[mode][name])
                                                  for name in ('mrr', 'ndcg_at_10')}
        else:
            baselines[mode] = dict(status='UNMEASURED', reason='BM25 is not applicable to image-only queries')
        # Diagnostic valid-only sweep: never select settings or look at test while tuning.
        if split == 'valid':
            field = 'efSearch' if hasattr(search.index, 'hnsw') else 'nprobe'
            owner = search.index.hnsw if field == 'efSearch' else search.index
            initial = getattr(owner, field)
            values = (cfg['search']['evaluation']['ef_search_sweep'] if field == 'efSearch'
                      else cfg['serving'].get('evaluation', {}).get('nprobe_sweep', [cfg['search']['faiss']['nprobe']]))
            if not values or any(type(v) is not int or v < 1 or (field == 'nprobe' and v > search.index.nlist) for v in values):
                raise ValueError('invalid configured ANN diagnostic sweep')
            try:
                for value in values:
                    setattr(owner, field, int(value))
                    rows = search.search(query_vectors, 10, eligible)
                    quality = score_rankings([[hit.product_id for hit in row] for row in rows], labels)
                    elapsed, effective = [], []
                    for i in range(cfg['benchmark']['warmup'] + cfg['benchmark']['requests']):
                        setattr(owner, field, int(value))
                        started = perf_counter()
                        search.search(query_vectors[i % len(query_vectors):i % len(query_vectors) + 1], 10, eligible)
                        duration = (perf_counter() - started) * 1000
                        if i >= cfg['benchmark']['warmup']:
                            elapsed.append(duration)
                            effective.append(getattr(owner, field))
                    tradeoff.append(dict(mode=mode, parameter=field, requested_value=int(value),
                        effective_min=min(effective), effective_max=max(effective), **quality,
                        vector_p95_ms=float(np.percentile(elapsed, 95)), warmup=cfg['benchmark']['warmup'],
                        requests=len(elapsed), scope='serial vector retrieval only; encoding/HTTP excluded; not the API latency gate'))
            finally:
                setattr(owner, field, initial)
    index_folder, _ = current_indexes(cfg)
    return dict(status='MEASURED', split=split, cutoff=cutoff.isoformat(),
        data_fingerprint=query_manifest['identity']['data_fingerprint'], primary=score_rankings(all_ranked, truth),
        per_mode=per_mode, bm25=baselines, tradeoff=tradeoff,
        query_fingerprint=query_manifest['fingerprint'], query_manifest_sha256=file_hash(folder / 'manifest.json'),
        evaluation_fingerprint=fingerprint(dict(query_fingerprint=query_manifest['fingerprint'], split=split,
                                               queries_per_mode=cfg['search']['evaluation']['queries_per_mode'], aggregation='macro query')),
        models=dict(embeddings=searcher.bundle['manifest'], index=json.loads((index_folder / 'manifest.json').read_text())),
        evaluation='observable attributes; independent augmented queries; no exact duplicate quality queries; labels never passed to the searcher',
        test_used_for_selection=False, settings_changed=False, runtime_threads=threads,
        runtime_policy='B inference thread guard reused; search/model/index configuration remains unchanged')
