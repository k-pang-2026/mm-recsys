"""Metadata-only normalized Two Tower with a shared item/history pathway."""
from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F

from src.recommendation.features import FeatureEncoder, ItemTable, ITEM_FIELDS, USER_FIELDS


class TwoTower(nn.Module):
    def __init__(self, encoder: FeatureEncoder, table: ItemTable, spec: dict):
        super().__init__()
        if spec.get('item_id_residual', False) or spec.get('history_pooling', 'mean') != 'mean':
            raise ValueError('v1 supports metadata-only item tower and mean history pooling')
        if spec.get('profile_categories', 'category_l3') != 'category_l3':
            raise ValueError('v1 purchase profiles use category_l3 distributions')
        width, hidden, dim = spec['embedding_dim'], spec['hidden_dim'], spec['dim']
        self.register_buffer('item_categories', torch.from_numpy(table.categories.copy()))
        self.register_buffer('item_prices', torch.from_numpy(table.prices.copy()))
        self.item_embeddings = nn.ModuleList([nn.Embedding(len(encoder.vocabs[f]) + 2, width, padding_idx=0)
                                              for f in ITEM_FIELDS])
        self.user_embeddings = nn.ModuleList([nn.Embedding(len(encoder.vocabs[f]) + 2, width, padding_idx=0)
                                              for f in USER_FIELDS])
        self.item_mlp = nn.Sequential(nn.Linear(len(ITEM_FIELDS) * width + 1, hidden), nn.ReLU(),
                                      nn.Linear(hidden, dim))
        self.user_mlp = nn.Sequential(nn.Linear(dim + len(USER_FIELDS) * width + encoder.profile_dim, hidden),
                                      nn.ReLU(), nn.Linear(hidden, dim))
        self.temperature = float(spec['temperature'])
        if self.temperature <= 0 or spec['loss'] != 'sampled_softmax':
            raise ValueError('positive temperature and sampled_softmax required')

    def encode_items(self, indices: torch.Tensor) -> torch.Tensor:
        categories = self.item_categories[indices]
        values = [embedding(categories[..., j]) for j, embedding in enumerate(self.item_embeddings)]
        encoded = self.item_mlp(torch.cat([*values, self.item_prices[indices]], dim=-1))
        # PAD must remain exactly zero even though MLP layers contain biases.
        return F.normalize(encoded, dim=-1) * indices.ne(0).unsqueeze(-1)

    def encode_users(self, history: torch.Tensor, demographics: torch.Tensor, profile: torch.Tensor) -> torch.Tensor:
        mask = history.ne(0).unsqueeze(-1)
        pooled = (self.encode_items(history) * mask).sum(dim=1) / mask.sum(dim=1).clamp_min(1)
        demos = [embedding(demographics[:, j]) for j, embedding in enumerate(self.user_embeddings)]
        return F.normalize(self.user_mlp(torch.cat([pooled, *demos, profile], dim=-1)), dim=-1)

    def forward(self, batch: dict[str, torch.Tensor]) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        users = self.encode_users(batch['history'], batch['demographics'], batch['profile'])
        items = self.encode_items(batch['items'])
        logits = torch.einsum('bd,bkd->bk', users, items) / self.temperature
        return logits, users, items


def weighted_loss(logits: torch.Tensor, weights: torch.Tensor) -> torch.Tensor:
    losses = F.cross_entropy(logits, torch.zeros(len(logits), dtype=torch.long, device=logits.device), reduction='none')
    return (losses * weights).sum() / weights.sum().clamp_min(1e-12)
