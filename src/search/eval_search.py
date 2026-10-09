"""Valid-only selection and separately invoked frozen test evaluation."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import numpy as np
import pandas as pd

from src.common.artifacts import file_hash, fingerprint, write_json
from src.common.config import load_config
from src.common.seed import set_seed
from src.evaluation.metrics import mrr, ndcg_at_k
from src.search.bm25 import BM25Search
from src.search.build_embeddings import atomic_array, search_root
from src.search.build_index import fuse
from src.search.encoder import check_vectors
from src.search.eval_support import ann_agreement, relevant_ids
from src.search.queries import freeze_queries
from src.search.searcher import Searcher


def encoded_queries(searcher: Searcher, folder: Path, split: str):
    queries = json.loads((folder/f'{split}.json').read_text())
    identity = {'query_manifest': file_hash(folder/'manifest.json'), 'split': split,
                'encoder': searcher.encoder.metadata, 'runtime_threads': searcher.cfg['search']['torch_threads']}
    path = search_root(searcher.cfg)/'query_vectors'/fingerprint(identity)
    path.mkdir(parents=True, exist_ok=True)
    if not (path/'manifest.json').exists():
        for mode in ('text', 'image'):
            active = [i for i, q in enumerate(queries) if q['query_text' if mode == 'text' else 'query_image_path']]
            values = [q['query_text'] if mode == 'text' else folder/q['query_image_path'] for q in (queries[i] for i in active)]
            encode = searcher.encoder.encode_texts if mode == 'text' else searcher.encoder.encode_images
            actual = encode(values); check_vectors(actual, searcher.encoder.dim, len(active))
            vectors = np.zeros((len(queries), searcher.encoder.dim), np.float32)
            vectors[active] = actual; atomic_array(path/f'{mode}.npy', vectors)
        write_json(path/'manifest.json', {'identity': identity,
                    'files': {f'{mode}.npy': file_hash(path/f'{mode}.npy') for mode in ('text', 'image')}})
    manifest = json.loads((path/'manifest.json').read_text())
    if manifest['identity'] != identity:
        raise ValueError('query-vector provenance mismatch')
    vectors = {}
    for mode in ('text', 'image'):
        name = f'{mode}.npy'
        if file_hash(path/name) != manifest['files'][name]:
            raise ValueError('changed query vector cache')
        vectors[mode] = np.load(path/name, allow_pickle=False)
        active = [i for i, q in enumerate(queries) if q['query_text' if mode == 'text' else 'query_image_path']]
        check_vectors(vectors[mode][active], searcher.encoder.dim, len(active))
    return queries, vectors


def score_rankings(rankings: list[list[str]], truth: list[set[str]]) -> dict:
    if any(not labels for labels in truth):
        raise ValueError('empty frozen truth must be reported, not silently excluded')
    return {'queries': len(rankings), 'mrr': mrr(rankings, truth),
            'ndcg_at_10': float(np.mean([ndcg_at_k(row, labels, 10) for row, labels in zip(rankings, truth)])),
            'mean_relevant_items': float(np.mean([len(labels) for labels in truth]))}


def evaluate(cfg: dict, split: str, sweep=False) -> dict:
    if sweep and split != 'valid':
        raise ValueError('model/index/fusion selection may only use valid queries')
    folder = freeze_queries(cfg); query_manifest = json.loads((folder/'manifest.json').read_text())
    searcher = Searcher(cfg); queries, vectors = encoded_queries(searcher, folder, split)
    cutoff = pd.Timestamp(query_manifest['identity']['cutoffs'][split])
    eligible = searcher.eligible_ids(cutoff); eligible_positions = [i for i, id_ in enumerate(searcher.bundle['ids']) if id_ in eligible]
    products = searcher.products.reset_index()
    truths = [relevant_ids(products, q['relevance_attributes'], q['mode'], cutoff) for q in queries]
    evaluation_identity = {'query_fingerprint': query_manifest['fingerprint'], 'split': split,
                           'cutoff': str(cutoff), 'rule_version': query_manifest['identity']['version'],
                           'aggregation': 'macro_query, balanced modes, binary multi-relevant NDCG@10'}
    all_ranked = [None]*len(queries); mode_results = {}; experiments = []; selected = {}
    for mode in ('text', 'image', 'hybrid'):
        active = [i for i, q in enumerate(queries) if q['mode'] == mode]
        mode_truth = [truths[i] for i in active]
        galleries = ['text', 'image'] if mode != 'hybrid' else ['text', 'image', 'hybrid']
        if not sweep:
            galleries = [cfg['search']['modes'][mode]]
        best = None
        for gallery in galleries:
            weights = cfg['search']['evaluation']['fusion_sweep'] if mode == 'hybrid' and sweep else [cfg['search']['query_fusion']['text_weight']]
            for weight in weights:
                query_vectors = (fuse(vectors['text'][active], vectors['image'][active],
                                      {'text_weight': weight, 'image_weight': 1-weight}) if mode == 'hybrid' else vectors[mode][active])
                search = searcher.indexes[gallery]
                efs = cfg['search']['evaluation']['ef_search_sweep'] if sweep else [cfg['search']['faiss']['ef_search']]
                for ef in efs:
                    if hasattr(search.index, 'hnsw'):
                        search.index.hnsw.efSearch = int(ef)
                    hits = search.search(query_vectors, 10, eligible)
                    ranked = [[hit.product_id for hit in row] for row in hits]
                    measured = score_rankings(ranked, mode_truth)
                    candidate = dict(mode=mode, gallery=gallery, text_weight=weight, ef_search=ef, **measured)
                    experiments.append(candidate)
                    choice = (measured['ndcg_at_10'], measured['mrr'], -int(ef))
                    if best is None or choice > best[0]:
                        best = (choice, candidate, ranked, hits, query_vectors)
        _, chosen, ranked, hits, query_vectors = best
        mode_results[mode] = chosen; selected[mode] = {'gallery': chosen['gallery'], 'text_weight': chosen['text_weight'], 'ef_search': chosen['ef_search']}
        for i, row in zip(active, ranked):
            all_ranked[i] = row
        source_vectors = searcher.bundle[chosen['gallery']] if chosen['gallery'] != 'hybrid' else fuse(
            searcher.bundle['text'], searcher.bundle['image'], cfg['search']['fusion'])
        eligible_lookup = {searcher.bundle['ids'][position]: i for i, position in enumerate(eligible_positions)}
        labels = np.array([[eligible_lookup[h.product_id] for h in row] for row in hits])
        scores = np.array([[h.score for h in row] for row in hits], np.float32)
        mode_results[mode]['ann_vs_exact'] = ann_agreement(source_vectors[eligible_positions], query_vectors, scores, labels, 10)
    audit = json.loads((searcher.bundle['folder']/'text_audit.json').read_text())
    bm25 = BM25Search(searcher.bundle['ids'], [q['raw'] for q in audit])
    baseline = {}
    for mode in ('text', 'hybrid'):
        active = [i for i, q in enumerate(queries) if q['mode'] == mode]
        ranked = [[h.product_id for h in bm25.search(queries[i]['query_text'], 10, eligible)] for i in active]
        baseline[mode] = score_rankings(ranked, [truths[i] for i in active])
    baseline['image'] = {'status': 'NOT_APPLICABLE', 'reason': 'image-only has no text query'}
    primary = score_rankings(all_ranked, truths)
    per_query = [{'query_id': q['query_id'], 'mode': q['mode'], 'ranked_ids': ranked,
                  'relevant_count': len(truth), 'reciprocal_rank': mrr([ranked], [truth]),
                  'ndcg_at_10': ndcg_at_k(ranked, truth, 10)} for q, ranked, truth in zip(queries, all_ranked, truths)]
    result = {'scale': cfg['scale'], 'split': split, 'status': 'MEASURED', 'data_fingerprint': query_manifest['identity']['data_fingerprint'],
              'config_fingerprint': fingerprint(cfg), 'evaluation_fingerprint': fingerprint(evaluation_identity),
              'evaluation': evaluation_identity, 'query_manifest_sha256': file_hash(folder/'manifest.json'),
              'model_fingerprint': searcher.bundle['manifest']['fingerprint'], 'eligible_catalog': len(eligible),
              'primary': primary, 'per_mode': mode_results, 'bm25': baseline, 'selected': selected,
              'experiments': experiments if sweep else [], 'per_query': per_query,
              'test_scores_used_for_selection': False, 'http_p95_ms': None,
              'targets': {'mrr': cfg['targets']['mrr'], 'ndcg_at_10': cfg['targets']['ndcg_at_10']},
              'relevance_labels_passed_to_searcher': False, 'exact_duplicate_quality_queries': 0}
    output = Path(f'docs/results/search_{split}_{cfg["scale"]}.json'); write_json(output, result)
    if sweep:
        selection = {'scale': cfg['scale'], 'data_fingerprint': result['data_fingerprint'],
                     'query_fingerprint': query_manifest['fingerprint'], 'selected_on': 'valid',
                     'selected': selected, 'gallery_fusion': cfg['search']['fusion'],
                     'source': str(output), 'sha256': file_hash(output)}
        write_json(search_root(cfg)/'selection.json', selection)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--split', choices=['valid', 'test'], default='valid'); parser.add_argument('--sweep', action='store_true')
    args = parser.parse_args(); cfg = load_config(); set_seed(cfg['seed'])
    if args.split == 'test':
        selection = json.loads((search_root(cfg)/'selection.json').read_text())
        if selection['selected_on'] != 'valid' or file_hash(Path(selection['source'])) != selection['sha256']:
            raise ValueError('frozen valid selection evidence required before test')
        frozen = json.loads((freeze_queries(cfg)/'manifest.json').read_text())
        if (selection['data_fingerprint'] != frozen['identity']['data_fingerprint'] or
                selection['query_fingerprint'] != frozen['fingerprint'] or
                selection['gallery_fusion'] != cfg['search']['fusion']):
            raise ValueError('test data/query/gallery differs from valid selection')
        for mode, chosen in selection['selected'].items():
            if cfg['search']['modes'][mode] != chosen['gallery']:
                raise ValueError('test configuration differs from valid-selected gallery')
            if mode == 'hybrid' and abs(cfg['search']['query_fusion']['text_weight']-chosen['text_weight']) > 1e-9:
                raise ValueError('test fusion differs from valid selection')
        if cfg['search']['faiss']['ef_search'] != max(c['ef_search'] for c in selection['selected'].values()):
            raise ValueError('test efSearch differs from valid-selected global setting')
    result = evaluate(cfg, args.split, args.sweep)
    print(json.dumps({'scale': result['scale'], 'split': args.split, 'primary': result['primary'],
                      'selected': result['selected'], 'per_mode': result['per_mode']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
