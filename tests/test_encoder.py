from pathlib import Path
from types import SimpleNamespace
import numpy as np
from PIL import Image
import pytest
import torch

from src.common.config import load_config
from src.search.encoder import CLIPEncoder, check_vectors, decode_rgb, unit_vectors
from src.search.text import normalize_text


def test_aliases_are_shared_and_unknown_terms_are_reported():
    result = normalize_text('검은색 오버핏 티셔츠 특이한소재')
    assert result.encoded == 'black oversized t-shirt 특이한소재'
    assert result.unknown_terms == ('특이한소재',)
    assert ('티셔츠', 't-shirt') in result.applied_aliases
    assert normalize_text('a BLACK shirt').encoded == 'a black shirt'
    with pytest.raises(ValueError):
        normalize_text(' ')


@pytest.mark.parametrize('bad', [np.zeros((1, 4)), np.full((1, 4), np.nan), np.ones(4)])
def test_zero_nonfinite_and_wrong_shape_are_rejected(bad):
    with pytest.raises(ValueError):
        unit_vectors(bad, 4)


def test_decoding_loads_rgb_and_rejects_corrupt_images(tmp_path):
    good = tmp_path/'gray.png'; Image.new('L', (20, 20)).save(good)
    assert decode_rgb(good).mode == 'RGB'
    bad = tmp_path/'bad.png'; bad.write_bytes(b'invalid PNG')
    with pytest.raises(ValueError, match='invalid'):
        decode_rgb(bad)


def test_encoder_uses_projected_inference_and_model_max_length(monkeypatch):
    """Fixture proves API/preprocessing behavior; real weights are verified by search.verify."""
    import transformers
    cfg = load_config(); revision = cfg['search']['clip_revision']; calls = []

    class Inputs(dict):
        def to(self, device):
            return self

    class Processor:
        def __call__(self, **kwargs):
            calls.append(kwargs)
            if 'images' in kwargs:
                assert all(image.mode == 'RGB' for image in kwargs['images'])
                return Inputs(pixel_values=torch.ones(len(kwargs['images']), 1))
            return Inputs(input_ids=torch.ones(len(kwargs['text']), 1))

    class Model:
        config = SimpleNamespace(projection_dim=4, _commit_hash=revision,
                                 text_config=SimpleNamespace(max_position_embeddings=77))
        def to(self, device):
            return self
        def eval(self):
            return self
        def get_text_features(self, input_ids):
            assert torch.is_inference_mode_enabled()
            return torch.ones(len(input_ids), 4)
        def get_image_features(self, pixel_values):
            assert torch.is_inference_mode_enabled()
            return torch.ones(len(pixel_values), 4)

    monkeypatch.setattr(transformers.CLIPModel, 'from_pretrained', lambda *a, **kw: Model())
    monkeypatch.setattr(transformers.CLIPProcessor, 'from_pretrained', lambda *a, **kw: Processor())
    encoder = CLIPEncoder(cfg)
    check_vectors(encoder.encode_texts(['검은색 셔츠 '*200]), 4, 1)
    check_vectors(encoder.encode_images([Image.new('L', (10, 10))]), 4, 1)
    assert calls[0]['truncation'] and calls[0]['max_length'] == 77
    assert calls[0]['text'][0].startswith('black shirt')


def test_encoder_rejects_wrong_checkpoint_revision(monkeypatch):
    import transformers
    model = SimpleNamespace(config=SimpleNamespace(projection_dim=4, _commit_hash='wrong',
                            text_config=SimpleNamespace(max_position_embeddings=77)))
    model.to = lambda device: model; model.eval = lambda: model
    monkeypatch.setattr(transformers.CLIPModel, 'from_pretrained', lambda *a, **kw: model)
    monkeypatch.setattr(transformers.CLIPProcessor, 'from_pretrained', lambda *a, **kw: object())
    with pytest.raises(ValueError, match='pinned'):
        CLIPEncoder(load_config())
