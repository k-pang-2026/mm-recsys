"""FP32 CPU graph optimization for the fixed-size CLIP query vision tower."""
from __future__ import annotations

import os
from typing import Any


def install_query_vision(encoder: Any) -> dict:
    if os.getenv('SERVING_OPTIMIZE_VISION', '1') != '1':
        return dict(enabled=False, reason='explicitly disabled')
    if getattr(encoder, 'device', None) != 'cpu' or not hasattr(getattr(encoder, 'model', None), 'vision_model'):
        return dict(enabled=False, reason='not a CPU CLIP query encoder')
    existing = getattr(encoder, '_docker_vision_optimization', None)
    if existing is not None:
        return existing
    import torch
    from src.search.encoder import unit_vectors

    class QueryVision(torch.nn.Module):
        def __init__(self, model: Any):
            super().__init__()
            self.vision = model.vision_model
            self.projection = model.visual_projection

        def forward(self, pixels: torch.Tensor) -> torch.Tensor:
            return self.projection(self.vision(pixel_values=pixels, return_dict=False)[1])

    model = encoder.model
    size = int(model.config.vision_config.image_size)
    expected = (1, 3, size, size)
    original = model.get_image_features
    example = torch.zeros(expected, dtype=torch.float32)
    with torch.inference_mode():
        module = QueryVision(model).eval()
        reference = original(pixel_values=example)
        traced = torch.jit.trace(module, example, check_trace=True)
        optimized = torch.jit.optimize_for_inference(traced)
        actual = optimized(example)
        difference = abs(unit_vectors(reference.numpy()) - unit_vectors(actual.numpy())).max().item()
    if actual.dtype != torch.float32 or difference > 1e-5:
        raise ValueError('FP32 query vision optimization failed its startup numerical check')

    def image_features(pixel_values: torch.Tensor, **kwargs: Any) -> torch.Tensor:
        # The public API processor always produces batch-one fixed-size pixels.
        # Keep the original path for any explicit nonstandard encoder call.
        if (tuple(pixel_values.shape) != expected or pixel_values.device.type != 'cpu'
                or pixel_values.dtype != torch.float32 or kwargs):
            return original(pixel_values=pixel_values, **kwargs)
        return optimized(pixel_values)

    model.get_image_features = image_features
    state = dict(enabled=True, implementation='torch.jit.optimize_for_inference', dtype='float32',
                 query_shape=list(expected), startup_max_abs_vector_error=difference,
                 process_environment={key: os.getenv(key) for key in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS')},
                 scope='same pinned FP32 weights and preprocessing; CPU query vision graph only; no response cache')
    # Keep quality-query caches separate from the original eager/batched path.
    # Catalog embeddings are loaded and verified before this runtime-only hook.
    encoder.metadata = {**getattr(encoder, 'metadata', {}), 'query_runtime': dict(
        version=1, implementation=state['implementation'], dtype='float32',
        shape=list(expected), threads=torch.get_num_threads(), process_environment=state['process_environment'])}
    encoder.batch_size = 1
    encoder._docker_vision_optimization = state
    return state
