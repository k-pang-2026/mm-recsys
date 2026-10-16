"""Deployment paths stay isolated from committed B/C measurement evidence."""
from __future__ import annotations

import copy
from pathlib import Path

from src.common.config import load_config


def runtime_config(cfg: dict | None = None) -> dict:
    value = copy.deepcopy(cfg if cfg is not None else load_config())
    value['paths']['results_dir'] = f"docs/results/docker/runtime/{value['scale']}"
    return value


def config_path(cfg: dict) -> Path:
    return Path(cfg['paths']['model_dir']) / '.docker' / 'config.yaml'
