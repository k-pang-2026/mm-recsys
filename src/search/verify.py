"""Real checkpoint/vector/index integrity diagnostics; this is not B2b acceptance."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import platform
import numpy as np
import pandas as pd
from pathlib import Path

from src.common.artifacts import file_hash, fingerprint, write_json
from src.common.config import load_config
from src.common.seed import set_seed
from src.search.bm25 import BM25Search
from src.search.build_embeddings import current_bundle
from src.search.build_index import current_indexes, fuse
from src.search.encoder import CLIPEncoder, check_vectors
from src.search.eval_support import ann_agreement, exact_search
from src.search.index import SearchIndex
from src.search.text import normalize_text


def verify(cfg: dict) -> dict:
    folder, bundle = current_indexes(cfg)
    encoder = CLIPEncoder(cfg)
    if bundle['manifest']['identity']['encoder'] != encoder.metadata:
        raise ValueError('embedding encoder provenance differs from actual pinned checkpoint')
    products = pd.read_parquet(Path(cfg['paths']['data_dir'])/'products.parquet').set_index('product_id')
    selected = np.random.default_rng(cfg['seed']).choice(len(bundle['ids']), min(32, len(bundle['ids'])), replace=False)
    ids = [bundle['ids'][i] for i in selected]
    rows = products.loc[ids]
    text_queries = encoder.encode_texts(rows.description_en.tolist())
    image_queries = encoder.encode_images([Path(cfg['paths']['data_dir'])/path for path in rows.image_path])
    for mode, queries in [('text', text_queries), ('image', image_queries)]:
        check_vectors(queries, encoder.dim, len(ids))
        if not np.allclose(queries, bundle[mode][selected], atol=2e-5):
            raise ValueError(f'{mode} vectors do not reproduce with query preprocessing/ID alignment')
        scores, _ = exact_search(bundle[mode], queries, min(10, len(ids)))
        if not np.allclose(scores[:, 0], 1, atol=2e-5):
            raise ValueError(f'{mode} exact self-content similarity failed')
    diagnostics = {}
    combinations = [('text_to_text', 'text', text_queries, bundle['text']),
                    ('image_to_image', 'image', image_queries, bundle['image']),
                    ('text_to_image', 'image', text_queries, bundle['image']),
                    ('hybrid_to_hybrid', 'hybrid', fuse(text_queries, image_queries, cfg['search']['query_fusion']),
                     fuse(bundle['text'], bundle['image'], cfg['search']['fusion']))]
    for name, mode, queries, vectors in combinations:
        loaded = SearchIndex.load(folder, mode, bundle['manifest']['fingerprint'])
        scores, labels = loaded.index.search(queries, cfg['search']['evaluation']['ann_recall_k'])
        diagnostics[name] = ann_agreement(vectors, queries, scores, labels, scores.shape[1])
        again = SearchIndex.load(folder, mode, bundle['manifest']['fingerprint'])
        if loaded.search(queries, 10) != again.search(queries, 10):
            raise ValueError(f'save/load search parity failed: {mode}')
        if cfg['search']['faiss']['type'] == 'HNSW' and diagnostics[name]['max_reported_score_error'] > 2e-5:
            raise ValueError('HNSW score disagrees with normalized exact inner product')
    probes = ['a photo of a black shirt', 'a photo of red sneakers', 'a photo of blue jeans',
              'a photo of a white coat', 'a photo of a pink bag']
    query_vectors = encoder.encode_texts(probes)
    image_index = SearchIndex.load(folder, 'image', bundle['manifest']['fingerprint'])
    cross_modal = []
    for query, hits in zip(probes, image_index.search(query_vectors, 5)):
        cross_modal.append({'query': normalize_text(query).to_dict(), 'hits': [
            dict(asdict(hit), **products.loc[hit.product_id, ['category_l1', 'category_l3', 'color']].to_dict())
            for hit in hits]})
    audit = json.loads((bundle['folder']/'text_audit.json').read_text())
    bm25 = BM25Search(bundle['ids'], [record['raw'] for record in audit])
    baseline_hits = bm25.search('검은색 셔츠', 10)
    result = {
        'stage': 'B2a', 'status': 'PASS', 'scale': cfg['scale'], 'seed': cfg['seed'],
        'data_fingerprint': bundle['manifest']['identity']['data_fingerprint'],
        'config_fingerprint': fingerprint(cfg), 'count': len(bundle['ids']), 'projection_dim': encoder.dim,
        'encoder': encoder.metadata, 'environment': {'platform': platform.platform(), 'python': platform.python_version()},
        'embedding_fingerprint': bundle['manifest']['fingerprint'],
        'index_fingerprint': json.loads((folder/'manifest.json').read_text())['fingerprint'],
        'manifests': {'embeddings': {'path': str(bundle['folder']/'manifest.json'), 'sha256': file_hash(bundle['folder']/'manifest.json')},
                      'indexes': {'path': str(folder/'manifest.json'), 'sha256': file_hash(folder/'manifest.json')}},
        'content_cache': bundle['manifest']['content_cache'],
        'query_preprocessing_reproduction': {'text': 'PASS', 'image': 'PASS', 'query_count': len(ids)},
        'self_content_exact_similarity': {'text': 'PASS', 'image': 'PASS'},
        'save_load_parity': 'PASS', 'ann_diagnostics': diagnostics,
        'cross_modal_content_inspection': cross_modal, 'bm25_alias_sanity': [asdict(hit) for hit in baseline_hits],
        'final_search_acceptance': 'UNMEASURED', 'mrr': None, 'ndcg_at_10': None, 'http_p95_ms': None,
        'limitations': ['ANN overlap compares vectors, not human/attribute relevance',
                        'self-content retrieval is a duplicate sanity test, not quality evaluation',
                        'cross-modal category/color rankings are recorded without a fabricated quality threshold',
                        'B2b frozen queries, HTTP service, full test quality and latency remain unmeasured',
                        'seed is fixed; threaded HNSW insertion can vary across platforms/runs'],
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path); args = parser.parse_args()
    cfg = load_config(); set_seed(cfg['seed'])
    result = verify(cfg)
    output = args.output or Path(f'docs/results/search_b2a_{cfg["scale"]}.json')
    write_json(output, result)
    print(json.dumps({key: result[key] for key in ('status', 'scale', 'count', 'projection_dim', 'ann_diagnostics',
                                                   'final_search_acceptance')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
