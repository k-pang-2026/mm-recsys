"""The query graph must still depend on pixels and preserve FP32 model weights."""
from types import SimpleNamespace
import os
import subprocess
import sys

import pytest
import torch

from docker.vision import install_query_vision
from docker.runtime import configure_process_environment


class Vision(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.linear = torch.nn.Linear(3, 8)

    def forward(self, pixel_values, return_dict=False):
        pooled = self.linear(pixel_values.mean(dim=(-2, -1)))
        return pixel_values, pooled


class Model(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.vision_model = Vision()
        self.visual_projection = torch.nn.Linear(8, 4)
        self.config = SimpleNamespace(vision_config=SimpleNamespace(image_size=4))

    def get_image_features(self, pixel_values, **kwargs):
        return self.visual_projection(self.vision_model(pixel_values, False)[1])


def test_query_graph_is_input_dependent_fp32_and_nonstandard_batches_use_original(monkeypatch):
    monkeypatch.setenv('SERVING_OPTIMIZE_VISION', '1')
    model = Model().eval()
    encoder = SimpleNamespace(model=model, device='cpu')
    weights = {name: value.clone() for name, value in model.state_dict().items()}
    images = [torch.zeros(1, 3, 4, 4), torch.ones(1, 3, 4, 4), torch.ones(2, 3, 4, 4)]
    with torch.inference_mode():
        expected = [model.get_image_features(x) for x in images]
        state = install_query_vision(encoder)
        actual = [model.get_image_features(x) for x in images]
    assert state['enabled'] and state['dtype'] == 'float32'
    assert install_query_vision(encoder) is state
    assert not torch.equal(actual[0], actual[1])
    assert all(torch.allclose(a, b, atol=1e-6, rtol=1e-6) for a, b in zip(actual, expected))
    assert all(torch.equal(value, model.state_dict()[name]) for name, value in weights.items())


def test_disabled_query_optimization_preserves_original_method(monkeypatch):
    monkeypatch.setenv('SERVING_OPTIMIZE_VISION', '0')
    model = Model().eval()
    encoder = SimpleNamespace(model=model, device='cpu')
    original = model.get_image_features
    assert install_query_vision(encoder)['enabled'] is False
    assert model.get_image_features == original


def test_inference_budget_is_initialized_before_native_library_imports():
    env = {**os.environ, 'SERVING_THREADS': '2', 'OMP_NUM_THREADS': '1',
           'MKL_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1'}
    code = "from docker.runtime import configure_process_environment; s=configure_process_environment(); import torch; assert set(s.values())=={'2'}; assert torch.get_num_threads()==2"
    subprocess.run([sys.executable, '-c', code], env=env, check=True, timeout=60)


def test_late_pool_configuration_is_rejected_without_changing_environment(monkeypatch):
    monkeypatch.setenv('SERVING_THREADS', '2')
    for name in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
        monkeypatch.setenv(name, '1')
    with pytest.raises(ValueError, match='before importing'):
        configure_process_environment()
    assert os.environ['OMP_NUM_THREADS'] == '1'
