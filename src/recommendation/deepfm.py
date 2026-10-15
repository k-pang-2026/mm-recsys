"""Shared linear + FM + DNN trunk, CTR and click-conditional CVR heads."""
from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F


class DeepFM(nn.Module):
    def __init__(self, cardinalities: list[int], dense_dim: int, spec: dict):
        super().__init__()
        dim = int(spec['embedding_dim'])
        self.embeddings = nn.ModuleList([nn.Embedding(n, dim) for n in cardinalities])
        self.linear = nn.ModuleList([nn.Embedding(n, 2) for n in cardinalities])
        self.dense_embeddings = nn.Parameter(torch.empty(dense_dim, dim))
        nn.init.normal_(self.dense_embeddings, std=0.01)
        self.dense_linear = nn.Linear(dense_dim, 2)
        width = len(cardinalities)*dim + dense_dim
        layers = []
        for hidden in spec['hidden_dims']:
            layers.extend([nn.Linear(width, hidden), nn.ReLU()]); width = hidden
        self.dnn = nn.Sequential(*layers, nn.Linear(width, 2))
        self.fm_scale = nn.Parameter(torch.ones(2))

    def forward(self, sparse: torch.Tensor, dense: torch.Tensor) -> torch.Tensor:
        embedded = torch.stack([e(sparse[:, j]) for j, e in enumerate(self.embeddings)], dim=1)
        fields = torch.cat([embedded, dense.unsqueeze(-1)*self.dense_embeddings], dim=1)
        fm = 0.5*(fields.sum(1).square()-fields.square().sum(1)).sum(-1, keepdim=True)
        linear = sum(e(sparse[:, j]) for j, e in enumerate(self.linear)) + self.dense_linear(dense)
        return linear + fm*self.fm_scale + self.dnn(torch.cat([embedded.flatten(1), dense], dim=1))


def loss(logits: torch.Tensor, targets: torch.Tensor, masks: torch.Tensor, cvr_weight: float) -> torch.Tensor:
    weights = logits.new_tensor([1., cvr_weight])
    losses = F.binary_cross_entropy_with_logits(logits, targets, reduction='none')
    return ((losses*masks).sum(0)/masks.sum(0).clamp_min(1)*weights).sum()
