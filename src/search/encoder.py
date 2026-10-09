"""Pinned projected CLIP encoders, with identical catalog/query preprocessing."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence
import numpy as np
from PIL import Image, UnidentifiedImageError

from src.search.text import ALIASES, PREPROCESS_VERSION, normalize_text
from src.common.artifacts import fingerprint


def unit_vectors(values: np.ndarray, dim: int | None = None) -> np.ndarray:
    values = np.asarray(values, dtype=np.float32)
    if values.ndim != 2 or (dim is not None and values.shape[1] != dim):
        raise ValueError('embedding shape must be (N, projection_dim)')
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    if not np.isfinite(values).all() or np.any(norms <= 1e-12):
        raise ValueError('nonfinite or zero embedding; no fallback is allowed')
    return np.ascontiguousarray(values / norms, dtype=np.float32)


def check_vectors(values: np.ndarray, dim: int, count: int | None = None) -> None:
    if values.dtype != np.float32 or values.ndim != 2 or values.shape[1] != dim:
        raise ValueError('expected float32 projected vectors')
    if count is not None and len(values) != count:
        raise ValueError('embedding/ID count mismatch')
    if not np.isfinite(values).all() or not np.allclose(np.linalg.norm(values, axis=1), 1, atol=1e-5):
        raise ValueError('embeddings must be finite and L2 normalized')


def decode_rgb(value: str | Path | Image.Image) -> Image.Image:
    try:
        if isinstance(value, Image.Image):
            return value.convert('RGB').copy()
        with Image.open(value) as image:
            image.load()
            return image.convert('RGB')
    except (OSError, ValueError, UnidentifiedImageError) as error:
        raise ValueError(f'invalid product/query image: {value}') from error


class CLIPEncoder:
    def __init__(self, cfg: dict):
        # Hugging Face reads cache environment while importing its modules.
        os.environ.setdefault('HF_HOME', str(Path(__file__).resolve().parents[2] / '.cache/huggingface'))
        import torch
        import transformers
        from transformers import CLIPModel, CLIPProcessor
        search = cfg['search']
        self.device = search.get('device', 'cpu')
        if self.device not in ('cpu', 'cuda') or (self.device == 'cuda' and not torch.cuda.is_available()):
            raise ValueError(f'unavailable CLIP device: {self.device}')
        self.batch_size = int(search['batch_size'])
        threads = int(search.get('torch_threads', 4))
        if self.batch_size <= 0 or not 1 <= threads <= 32:
            raise ValueError('positive batch_size and bounded torch_threads required')
        torch.set_num_threads(threads)
        revision = search['clip_revision']
        options = {'revision': revision, 'local_files_only': search.get('local_files_only', True)}
        self.model = CLIPModel.from_pretrained(search['clip_model'], **options).to(self.device).eval()
        self.processor = CLIPProcessor.from_pretrained(search['clip_model'], **options)
        self.dim = int(self.model.config.projection_dim)
        self.max_length = int(self.model.config.text_config.max_position_embeddings)
        if self.model.config._commit_hash != revision:
            raise ValueError('resolved CLIP checkpoint does not match pinned revision')
        self.metadata = {
            'model': search['clip_model'], 'model_revision': revision, 'processor_revision': revision,
            'projection_dim': self.dim, 'normalization': 'L2', 'dtype': 'float32',
            'max_text_length': self.max_length, 'preprocess_version': PREPROCESS_VERSION,
            'alias_fingerprint': fingerprint(ALIASES), 'transformers': transformers.__version__,
            'torch': torch.__version__, 'device': self.device,
        }

    def encode_texts(self, texts: Sequence[str]) -> np.ndarray:
        import torch
        output = []
        for start in range(0, len(texts), self.batch_size):
            batch = [normalize_text(value).encoded for value in texts[start:start+self.batch_size]]
            inputs = self.processor(text=batch, return_tensors='pt', padding=True,
                                    truncation=True, max_length=self.max_length).to(self.device)
            with torch.inference_mode():
                projected = self.model.get_text_features(**inputs)
            output.append(unit_vectors(projected.float().cpu().numpy(), self.dim))
        return np.concatenate(output) if output else np.empty((0, self.dim), np.float32)

    def encode_images(self, images: Sequence[str | Path | Image.Image]) -> np.ndarray:
        import torch
        output = []
        for start in range(0, len(images), self.batch_size):
            batch = [decode_rgb(value) for value in images[start:start+self.batch_size]]
            try:
                inputs = self.processor(images=batch, return_tensors='pt').to(self.device)
                with torch.inference_mode():
                    projected = self.model.get_image_features(**inputs)
                output.append(unit_vectors(projected.float().cpu().numpy(), self.dim))
            finally:
                for image in batch:
                    image.close()
        return np.concatenate(output) if output else np.empty((0, self.dim), np.float32)
