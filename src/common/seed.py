from __future__ import annotations
import os
import random
import numpy as np
import torch

def set_seed(seed: int = 42) -> None:
    """Seed python/numpy/torch(+CUDA). Call as set_seed(cfg["seed"])."""
    # hash seed는 프로세스 시작 전에 설정해야 한다. 여기서 설정하면 자식 프로세스에만 적용.
    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.use_deterministic_algorithms(True, warn_only=True)
