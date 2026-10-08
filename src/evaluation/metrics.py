from __future__ import annotations
from typing import Sequence, Union
import numpy as np
from sklearn.metrics import log_loss as _log_loss
from sklearn.metrics import roc_auc_score

# truth: 쿼리당 단일 정답(str) 또는 정답 집합(set[str])
Truth = Union[str, set[str]]

def _to_set(t: Truth) -> set[str]:
    return {t} if isinstance(t, str) else set(t)

def mrr(ranked: Sequence[Sequence[str]], truth: Sequence[Truth]) -> float:
    if len(ranked) != len(truth):
        raise ValueError("ranked/truth lengths differ")
    rr: list[float] = []
    for r, t in zip(ranked, truth):
        rel = _to_set(t)
        rank = next((i + 1 for i, x in enumerate(r) if x in rel), None)
        rr.append(1.0 / rank if rank else 0.0)
    return float(np.mean(rr)) if rr else 0.0

def ndcg_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    if k <= 0 or len(ranked) != len(set(ranked)):
        raise ValueError("k must be positive and ranked IDs unique")
    dcg = sum(1.0 / np.log2(i + 2) for i, x in enumerate(ranked[:k]) if x in relevant)
    idcg = sum(1.0 / np.log2(i + 2) for i in range(min(len(relevant), k)))
    return float(dcg / idcg) if idcg > 0 else 0.0

def hit_rate_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    return float(any(x in relevant for x in ranked[:k]))

def recall_at_k(ranked: Sequence[str], relevant: set[str], k: int) -> float:
    if k <= 0:
        raise ValueError("k must be positive")
    return len(set(ranked[:k]) & relevant) / len(relevant) if relevant else 0.0

def coverage(recommended: set[str], n_total_items: int) -> float:
    """unique recommended items / all catalog items. 평가 사용자 집합과 N 은 config 에 고정."""
    return len(recommended) / n_total_items if n_total_items > 0 else 0.0

def auc(y_true: Sequence[int], y_score: Sequence[float]) -> float:
    y = np.asarray(y_true)
    if len(np.unique(y)) < 2:
        return float("nan")  # 정의되지 않음: 호출 측에서 '미측정/undefined'로 보고
    return float(roc_auc_score(y, y_score))

def logloss(y_true: Sequence[int], y_prob: Sequence[float], eps: float = 1e-7) -> float:
    p = np.clip(np.asarray(y_prob, dtype=float), eps, 1.0 - eps)
    return float(_log_loss(np.asarray(y_true), p, labels=[0, 1]))

def category_entropy(categories: Sequence[str]) -> float:
    if len(categories) == 0:
        return 0.0
    _, counts = np.unique(np.asarray(categories), return_counts=True)
    p = counts / counts.sum()
    return float(-(p * np.log2(p)).sum())
