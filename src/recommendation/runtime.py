"""Inference thread setup for the pinned PyTorch/FAISS macOS ARM OpenMP conflict."""
from __future__ import annotations

import platform

import torch


def inference_threads(spec: dict) -> int:
    # Pinned macOS ARM wheels load different libomp runtimes. Avoid entering parallel
    # regions in both libraries; this changes execution resources, not model/config data.
    return 1 if platform.system() == 'Darwin' and platform.machine() == 'arm64' else int(spec['threads'])


def configure_inference(spec: dict, with_faiss: bool = False) -> int:
    threads = inference_threads(spec)
    torch.set_num_threads(threads)
    if with_faiss:
        import faiss
        faiss.omp_set_num_threads(threads)
    return threads
