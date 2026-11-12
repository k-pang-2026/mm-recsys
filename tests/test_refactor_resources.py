"""Preserve bundle compatibility, temporal labels and A/B isolation while reusing work."""
import copy
import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
import torch

from src.common.artifacts import fingerprint, write_json, file_hash
from src.common.config import load_config
from src.recommendation.bundle_compat import candidate_scope
from src.recommendation.feature_store import RecommendationFeatureStore
from src.recommendation.service import create_service
from src.recommendation.testing import service_fixture


@pytest.mark.parametrize('component', ['candidate', 'ranking', 'session'])
def test_legacy_bundles_accept_only_original_clipping_value(tmp_path, component):
    cfg, data = service_fixture(tmp_path)
    old = copy.deepcopy(cfg)
    for name in ('candidate', 'ranking', 'session'):
        old['recommend'][name].pop('max_grad_norm')
    root = Path(cfg['paths']['model_dir']) / 'v1.0'
    path = root / 'meta.json'
    meta = json.loads(path.read_text())
    meta.update(training_spec=old['recommend']['candidate'], config_fingerprint=fingerprint(old['recommend']),
                candidate_scope_fingerprint=fingerprint(candidate_scope(old['recommend'])))
    index_path = root / 'index_manifest.json'
    index = json.loads(index_path.read_text())
    index['config_fingerprint'] = meta['config_fingerprint']
    write_json(index_path, index)
    meta['hashes']['index_manifest.json'] = file_hash(index_path)
    write_json(path, meta)
    for name in ('ranking', 'session'):
        path = root / name / 'meta.json'
        meta = json.loads(path.read_text())
        meta['config_fingerprint'] = fingerprint(old['recommend'][name])
        write_json(path, meta)
    store = RecommendationFeatureStore(cfg, data['products'])
    assert create_service(cfg, store) is not None
    cfg['recommend'][component]['max_grad_norm'] = 5.
    with pytest.raises(ValueError, match='config'):
        create_service(cfg, store)


@pytest.mark.parametrize('value', [0, -1, float('inf'), float('nan'), True, '10'])
def test_invalid_gradient_clip_config_is_rejected(tmp_path, value):
    import yaml
    cfg = load_config()
    cfg['recommend']['ranking']['max_grad_norm'] = value
    path = tmp_path / 'config.yaml'; path.write_text(yaml.safe_dump(cfg))
    with pytest.raises(ValueError, match='max_grad_norm'):
        load_config(str(path))


def test_ab_loads_each_model_once_and_keeps_mutable_state_isolated(tmp_path):
    from src.evaluation.ab_test import create_policies
    cfg, data = service_fixture(tmp_path)
    with patch('src.recommendation.service.read_data', side_effect=AssertionError('duplicate data read')), \
            patch('torch.load', wraps=torch.load) as loads:
        policies, metadata = create_policies(cfg, data, [0.])
    assert sorted(Path(call.args[0]).name for call in loads.call_args_list) == ['deepfm.pt', 'session.pt', 'two_tower.pt']
    a, b = (policies[key].service for key in ('control', 'treatment'))
    assert a.data is b.data is data and a.ranker is b.ranker
    assert a.store is not b.store and a._lock is not b._lock and a.cfg is not b.cfg
    assert set(metadata) == {'candidate', 'ranking', 'session'}
    assert metadata == a.bundle_metadata and metadata is not a.bundle_metadata


def test_selected_labels_match_original_and_do_not_build_unused_splits(tmp_path):
    from src.simulator.generate import generate
    from src.recommendation.train_deepfm import prepare, build_labels
    cfg = load_config()
    cfg['simulator'].update(n_products=400, n_users=24, n_events=6000, image_size=32)
    cfg['paths']['data_dir'] = str(tmp_path / 'data')
    generate(cfg)
    for split in ('valid', 'test'):
        _, expected, diagnostics = prepare(cfg, split)
        with patch('src.recommendation.train_deepfm.build_labels', wraps=build_labels) as build:
            data, selected, selected_diagnostics = prepare(cfg, split, label_splits=(split,))
        assert build.call_count == 1 and set(selected) == {split}
        pd.testing.assert_frame_equal(selected[split], expected[split])
        assert selected_diagnostics == {split: diagnostics[split]}
        if split == 'valid':
            assert 'test' not in data
    with pytest.raises(ValueError, match='temporal boundary'):
        prepare(cfg, 'valid', label_splits=('test',))
