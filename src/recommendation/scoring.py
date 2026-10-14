"""Inference policy independent of the frozen candidate/DeepFM training scopes."""
from __future__ import annotations

import numpy as np
from src.recommendation.reranking import RankedItem


def policy(spec: dict | None = None) -> dict:
    spec = spec or {'strategy': 'ctr_cvr'}
    strategy = spec.get('strategy', 'ctr_cvr')
    if strategy not in ('ctr_cvr', 'ctr', 'rank_fusion'):
        raise ValueError('unsupported recommendation scoring strategy')
    if strategy == 'rank_fusion':
        alpha = float(spec.get('alpha', 0.5))
        if not np.isfinite(alpha) or not 0 <= alpha <= 1:
            raise ValueError('rank fusion alpha must be finite and in [0,1]')
        return dict(strategy=strategy, alpha=alpha)
    return dict(strategy=strategy)


def score_items(products: list[str], probabilities: np.ndarray, spec: dict | None = None) -> list[RankedItem]:
    selected = policy(spec)
    values = np.asarray(probabilities)
    if values.shape != (len(products), 2) or not np.isfinite(values).all():
        raise ValueError('invalid/nonfinite recommendation probabilities')
    if (values < 0).any() or (values > 1).any() or len(set(products)) != len(products):
        raise ValueError('probabilities must be in [0,1] and candidates distinct')
    strategy = selected['strategy']
    if strategy == 'ctr_cvr':
        scores = values[:, 0] * values[:, 1]
        reason = 'DeepFM 클릭·구매 가능성'
    elif strategy == 'ctr':
        scores = values[:, 0]
        reason = 'DeepFM 클릭 가능성'
    else:
        count = len(products)
        # Zero-based ranks implement q(r)=(M-r)/(M-1) for one-based r.
        candidate_q = np.linspace(1., 0., count) if count > 1 else np.ones(count)
        ctr_order = sorted(range(count), key=lambda i: (-values[i, 0], products[i]))
        ctr_q = np.empty(count)
        for rank, index in enumerate(ctr_order):
            ctr_q[index] = 1. if count == 1 else (count - 1 - rank) / (count - 1)
        alpha = selected['alpha']
        scores = (1 - alpha) * candidate_q + alpha * ctr_q
        reason = '후보·클릭 순위 결합'
    return [RankedItem(product, float(score), reason) for product, score in zip(products, scores)]
