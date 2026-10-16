"""Apply one process thread budget after both shared factories have loaded."""
from __future__ import annotations

from typing import Any, AsyncIterator
import numpy as np

from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor, wait
import gc
import os
from pathlib import Path
import time

from src.common.artifacts import write_json
from docker.runtime import runtime_config


def apply_budget(threads: int) -> None:
    import torch
    import faiss
    torch.set_num_threads(threads)
    faiss.omp_set_num_threads(threads)


def stabilize_heap(enabled: bool) -> None:
    if enabled:
        gc.unfreeze()
        gc.collect()
        gc.freeze()


class BudgetedBackend:
    """Apply Torch/OpenMP policy in the actual AnyIO inference worker thread."""
    def __init__(self, backend, threads: int):
        self.backend, self.threads = backend, threads

    def __getattr__(self, name):
        return getattr(self.backend, name)

    def search(self, payload: Any) -> Any:
        apply_budget(self.threads)
        return self.backend.search(payload)

    def recommend(self, user_id: str, top_n: int) -> Any:
        apply_budget(self.threads)
        return self.backend.recommend(user_id, top_n)


class ParallelHybridSearcher:
    """Overlap independent read-only CLIP towers; preserve fusion and retrieval."""
    def __init__(self, original, pool: ThreadPoolExecutor, threads: int):
        self.original, self.pool, self.threads = original, pool, threads

    def __getattr__(self, name):
        return getattr(self.original, name)

    def _encode(self, method: str, value):
        apply_budget(self.threads)
        return getattr(self.original.encoder, method)([value])

    def encode(self, query_text: str | None=None, query_image: Any=None) -> tuple[str, np.ndarray]:
        has_text = isinstance(query_text, str) and bool(query_text.strip())
        if not has_text or query_image is None:
            return self.original.encode(query_text, query_image)
        from src.search.build_index import fuse
        with self.original._lock:
            text = self.pool.submit(self._encode, 'encode_texts', query_text)
            image = self.pool.submit(self._encode, 'encode_images', query_image)
            # The request owns the input image; finish both jobs even on failure.
            wait((text, image))
            return 'hybrid', fuse(text.result(), image.result(), self.original.cfg['search']['query_fusion'])

    def search(self, query_text: str | None=None, query_image: Any=None, k: int=10, cutoff: Any=None) -> Any:
        mode, vectors = self.encode(query_text, query_image)
        return mode, self.original.retrieve(mode, vectors, k, cutoff)


def wrap_backends(shared: Any, threads: int) -> None:
    for kind in ('search', 'recommend'):
        backend = getattr(shared.state, kind, None)
        if backend is not None and not isinstance(backend, BudgetedBackend):
            pool = getattr(shared.state, 'docker_encoder_pool', None)
            if kind == 'search':
                from docker.vision import install_query_vision
                encoder = getattr(getattr(backend, 'searcher', None), 'encoder', None)
                shared.state.docker_vision_optimization = install_query_vision(encoder)
            if kind == 'search' and pool is not None:
                backend.searcher = ParallelHybridSearcher(backend.searcher, pool, threads)
            setattr(shared.state, kind, BudgetedBackend(backend, threads))


class ReloadBudget:
    """C's compatible-bundle loader also configures threads; restore serving policy."""
    def __init__(self, app, shared, threads: int, freeze_heap: bool):
        self.app, self.shared, self.threads, self.freeze_heap = app, shared, threads, freeze_heap

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http' and scope['path'] == '/api/admin/reload':
            async def restored(message: dict) -> None:
                if message['type'] == 'http.response.start':
                    apply_budget(self.threads)
                    if message['status'] == 200:
                        wrap_backends(self.shared, self.threads)
                        stabilize_heap(self.freeze_heap)
                await send(message)
            try:
                await self.app(scope, receive, restored)
            finally:
                apply_budget(self.threads)
        else:
            await self.app(scope, receive, send)


def install_runtime_limits(shared: Any, cfg: dict) -> None:
    original = shared.router.lifespan_context
    threads = int(os.getenv('SERVING_THREADS', str(cfg['search']['torch_threads'])))
    if not 1 <= threads <= 32:
        raise ValueError('bounded process thread budget required')
    freeze_heap = os.getenv('SERVING_GC_FREEZE', '1') == '1'
    shared.add_middleware(ReloadBudget, shared=shared, threads=threads, freeze_heap=freeze_heap)

    @asynccontextmanager
    async def lifespan(application: Any) -> AsyncIterator[None]:
        async with original(application):
            import torch
            import faiss
            apply_budget(threads)
            pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='clip-tower')
            application.state.docker_encoder_pool = pool if os.getenv('SERVING_PARALLEL_HYBRID', '1') == '1' else None
            wrap_backends(application, threads)
            gc_starts = {}
            def gc_timing(phase: str, info: dict) -> None:
                generation = info['generation']
                if phase == 'start':
                    gc_starts[generation] = time.perf_counter()
                elif generation == 2 and generation in gc_starts:
                    print('GC generation2: ' + str(dict(elapsed_ms=(time.perf_counter()-gc_starts[generation])*1000,
                        at_ns=time.time_ns(), frozen_objects=gc.get_freeze_count())), flush=True)
            gc.callbacks.append(gc_timing)
            stabilize_heap(freeze_heap)
            state = dict(torch_threads=torch.get_num_threads(), faiss_threads=faiss.omp_get_max_threads(),
                         inference_worker_budget=True,
                         parallel_hybrid=application.state.docker_encoder_pool is not None,
                         vision_optimization=getattr(application.state, 'docker_vision_optimization', {}),
                         gc_enabled=gc.isenabled(), gc_freeze_enabled=freeze_heap,
                         gc_frozen_objects=gc.get_freeze_count(),
                         configured_search_threads=cfg['search']['torch_threads'],
                         configured_candidate_training_threads=cfg['recommend']['candidate']['threads'],
                         scope='one shared serving process; model weights and ranking policy unchanged')
            write_json(Path(cfg['paths']['results_dir']) / 'serving_runtime.json', state)
            print(f'SERVING RUNTIME: {state}', flush=True)
            try:
                yield
            finally:
                pool.shutdown(wait=True)
                gc.callbacks.remove(gc_timing)
                if freeze_heap:
                    gc.unfreeze()

    shared.router.lifespan_context = lifespan


# Preserve A's exact JSON/multipart app and C's API/CT routers and factories.
from src.search.api import app as app

install_runtime_limits(app.app, runtime_config())
