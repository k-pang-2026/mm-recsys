"""Measured metric rows shared by B8 evaluators; no invented missing values."""
from __future__ import annotations

import math
import platform
from pathlib import Path

from src.common.artifacts import file_hash, fingerprint

VERSION = 'evaluation-dashboard-v1'


def metric(name: str, value: float | None, cfg: dict, split: str,
           source: str, reason: str | None = None) -> dict:
    target = cfg['targets'].get(name)
    measured = value is not None and not isinstance(value, bool) and math.isfinite(float(value))
    status = 'UNMEASURED'
    if measured:
        status = ('PASS' if (value <= target if name.endswith('_ms') else value >= target)
                  else 'FAIL') if target is not None else 'MEASURED'
    return dict(name=name, value=float(value) if measured and value is not None else None, target=target,
                direction='max' if name.endswith('_ms') else 'min', status=status,
                split=split, source=source, reason=reason if not measured else None)


def relative_lift(value: float | None, baseline: float | None) -> float | None:
    return value / baseline - 1 if value is not None and baseline is not None and baseline != 0 else None


def identity(cfg: dict, manifest: dict, models: dict) -> dict:
    return dict(scale=cfg['scale'], seed=cfg['seed'], data_fingerprint=manifest['generation_fingerprint'],
                data_hashes=manifest['file_hashes'], config_fingerprint=fingerprint(cfg), models=models)


def sources(names: list[str]) -> dict:
    return {name: file_hash(Path(name)) for name in names}


def environment() -> dict:
    import os
    import subprocess
    import torch
    import faiss
    import numpy as np
    ram_bytes = None
    try:
        ram_bytes = (int(subprocess.check_output(['sysctl', '-n', 'hw.memsize'], text=True, stderr=subprocess.DEVNULL))
                     if platform.system() == 'Darwin' else os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES'))
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    docker: dict = dict(status='UNMEASURED')
    try:
        fields = subprocess.check_output(['docker', 'info', '--format', '{{.MemTotal}} {{.NCPU}} {{.ServerVersion}}'],
                                         text=True, stderr=subprocess.DEVNULL, timeout=10).split()
        docker = dict(status='MEASURED', memory_bytes=int(fields[0]), cpus=int(fields[1]), version=fields[2])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        pass
    return dict(platform=platform.platform(), python=platform.python_version(),
                cpu=platform.processor() or platform.machine(), logical_cpus=os.cpu_count(), ram_bytes=ram_bytes,
                docker_allocation=docker, benchmark_scope='native API/ML clients and Docker Redis; full service-container reproduction is unmeasured',
                torch=torch.__version__, numpy=np.__version__, faiss=faiss.__version__,
                torch_threads=torch.get_num_threads(), faiss_threads=faiss.omp_get_max_threads(),
                device='cpu', gpu_used=False, pythonhashseed=os.getenv('PYTHONHASHSEED'),
                nondeterminism='seeded CPU inference; cross-platform floating point may differ')
