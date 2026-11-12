"""Deployment paths stay isolated from committed B/C measurement evidence."""
from __future__ import annotations

import copy
import os
import sys
from pathlib import Path

from src.common.config import load_config


def configure_process_environment() -> dict[str, str]:
    """Initialize native inference pools before import; preparation/training keep their own budget."""
    threads = int(os.getenv('SERVING_THREADS', '2'))
    if not 1 <= threads <= 32:
        raise ValueError('bounded inference process thread budget required')
    settings = {key: str(threads) for key in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS')}
    if any(name in sys.modules for name in ('numpy', 'torch')) and any(
            os.environ.get(key) != value for key, value in settings.items()):
        raise ValueError('initialize inference CPU budget before importing numpy/torch')
    os.environ.update(settings)
    return settings


def runtime_config(cfg: dict | None = None) -> dict:
    value = copy.deepcopy(cfg if cfg is not None else load_config())
    base = os.getenv('RUNTIME_RESULTS_DIR', 'docs/results/docker/runtime-v44')
    value['paths']['results_dir'] = str(Path(base) / value['scale'])
    # Separate observed state when regenerating a catalog with the same product IDs.
    from src.common.artifacts import fingerprint
    value['serving'].setdefault('redis', {}).setdefault('namespace',
        f"mm-recsys:{value['scale']}:{fingerprint(value['paths']['data_dir'])[:12]}")
    return value


def config_path(cfg: dict) -> Path:
    return Path(cfg['paths']['model_dir']) / '.docker' / 'config.yaml'
