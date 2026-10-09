"""Exact-vector diagnostics are separate from attribute relevance quality."""
from __future__ import annotations

import faiss
import numpy as np
import pandas as pd
from src.search.encoder import check_vectors


def exact_search(vectors: np.ndarray, queries: np.ndarray, k: int):
    check_vectors(vectors, vectors.shape[1]); check_vectors(queries, vectors.shape[1])
    if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= len(vectors):
        raise ValueError('exact diagnostic k must be within catalog size')
    index = faiss.IndexFlatIP(vectors.shape[1]); index.add(np.ascontiguousarray(vectors))
    return index.search(np.ascontiguousarray(queries), k)


def ann_agreement(vectors: np.ndarray, queries: np.ndarray, ann_scores, ann_labels, k: int) -> dict:
    exact_scores, exact_labels = exact_search(vectors, queries, k)
    if ann_labels.shape != exact_labels.shape or ann_scores.shape != exact_scores.shape:
        raise ValueError('ANN/exact result shapes differ')
    agreement = []; tie_agreement = []; score_errors = []
    for row, (scores, labels) in enumerate(zip(ann_scores, ann_labels)):
        valid = labels[labels >= 0]
        if np.any(valid >= len(vectors)):
            raise ValueError('invalid ANN row label')
        if np.any(labels < -1) or len(set(valid)) != len(valid):
            raise ValueError('invalid or repeated ANN row label')
        agreement.append(len(set(valid) & set(exact_labels[row])) / k)
        # Many products share content: a different ID at the exact kth score is equivalent.
        true_scores = vectors[valid] @ queries[row]
        if not np.isfinite(scores[labels >= 0]).all():
            raise ValueError('nonfinite ANN score')
        score_errors.extend(np.abs(scores[labels >= 0]-true_scores).tolist())
        tie_agreement.append(float(np.sum(true_scores >= exact_scores[row, -1]-2e-5)) / k)
    return {'k': k, 'queries': len(queries), 'label_overlap_recall': float(np.mean(agreement)),
            'exact_score_tie_aware_agreement': float(np.mean(tie_agreement)),
            'max_reported_score_error': max(score_errors, default=0.0),
            'interpretation': 'ANN vs exact vector search; not relevance MRR/NDCG'}


def relevant_ids(products: pd.DataFrame, attributes: dict[str, str], mode: str,
                 cutoff: pd.Timestamp | None = None) -> set[str]:
    allowed = {'category_l1', 'color'} if mode == 'image' else {
        'category_l1', 'category_l2', 'category_l3', 'color', 'style', 'brand'}
    if mode not in ('text', 'image', 'hybrid') or set(attributes)-allowed:
        raise ValueError('relevance must use attributes observable in this query mode')
    if not attributes:
        raise ValueError('relevance requires explicit observable conditions')
    mask = pd.Series(True, index=products.index)
    if cutoff is not None:
        mask &= pd.to_datetime(products.created_at, utc=True) <= cutoff
    for key, value in attributes.items():
        mask &= products[key] == value
    return set(products.loc[mask, 'product_id'])
