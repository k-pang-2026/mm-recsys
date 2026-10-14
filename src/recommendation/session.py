"""GRU next-view encoder over frozen Two Tower item embeddings."""
from __future__ import annotations

import numpy as np
import torch
from torch import nn
from torch.nn import functional as F


class SessionEncoder(nn.Module):
    def __init__(self,item_vectors: np.ndarray,spec: dict):
        super().__init__()
        vectors=torch.from_numpy(item_vectors.astype(np.float32))
        self.items=nn.Embedding.from_pretrained(vectors,freeze=True,padding_idx=0)
        self.gru=nn.GRU(vectors.shape[1],int(spec['hidden_dim']),batch_first=True)
        self.projection=nn.Linear(int(spec['hidden_dim']),vectors.shape[1])

    def forward(self,sequences: torch.Tensor) -> torch.Tensor:
        # Right padding keeps the final actual event at length-1.
        lengths=sequences.ne(0).sum(1)
        output,_=self.gru(self.items(sequences))
        last=output[torch.arange(len(sequences),device=sequences.device),(lengths-1).clamp_min(0)]
        return F.normalize(self.projection(last),dim=-1)*lengths.gt(0).unsqueeze(-1)

    def combine(self,long_term: np.ndarray,sequences: torch.Tensor,spec: dict) -> np.ndarray:
        if spec['session_weight']<0 or spec['long_term_weight']<=0:
            raise ValueError('invalid session fusion weights')
        with torch.inference_mode():
            short=self(sequences).numpy()
        combined=spec['session_weight']*short+spec['long_term_weight']*long_term
        norms=np.linalg.norm(combined,axis=1,keepdims=True)
        return (combined/np.maximum(norms,1e-12)).astype(np.float32)


def sequence_for(products: list[str],table,max_length: int) -> torch.Tensor:
    known=[table.id_to_index[p] for p in products if p in table.id_to_index][-max_length:]
    sequence=np.zeros((1,max_length),np.int64); sequence[0,:len(known)]=known
    return torch.from_numpy(sequence)
