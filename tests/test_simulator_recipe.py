"""A sorted YAML roundtrip must never share identity with a different simulation."""
from __future__ import annotations

import copy
import numpy as np
import pytest
import yaml

from src.common.artifacts import fingerprint
from src.common.config import load_config
from src.simulator.catalog import make_catalog
from src.simulator.generate import generation_identity
from src.simulator.events import make_events
from src.simulator.users import make_users


def test_order_changing_yaml_gets_distinct_data_identity():
    cfg = copy.deepcopy(load_config())
    cfg['simulator']['n_products'] = 400
    sorted_cfg = yaml.safe_load(yaml.safe_dump(cfg, sort_keys=True))
    assert fingerprint(cfg) == fingerprint(sorted_cfg)
    assert fingerprint(generation_identity(cfg)) != fingerprint(generation_identity(sorted_cfg))
    a = make_catalog(cfg, np.random.default_rng(cfg['seed']))
    b = make_catalog(sorted_cfg, np.random.default_rng(cfg['seed']))
    assert not a.equals(b)


def test_preparation_roundtrip_preserves_catalog_and_data_identity():
    cfg = copy.deepcopy(load_config())
    cfg['simulator']['n_products'] = 400
    restored = yaml.safe_load(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False))
    assert fingerprint(generation_identity(cfg)) == fingerprint(generation_identity(restored))
    a = make_catalog(cfg, np.random.default_rng(cfg['seed']))
    b = make_catalog(restored, np.random.default_rng(cfg['seed']))
    assert a.equals(b)


@pytest.mark.parametrize('destination', ['exit', 'view', 'purchase'])
def test_cart_transition_zero_and_one_are_respected(destination):
    cfg = load_config()
    cfg['simulator'].update(n_products=400, n_users=40, n_events=2000, cold_user_ratio=0)
    cfg['simulator']['transitions']['view'] = {'cart': 1.0}
    cfg['simulator']['transitions']['cart'] = {
        name: float(name == destination) for name in ('purchase', 'view', 'exit')}
    rng = np.random.default_rng(cfg['seed'])
    products, users = make_catalog(cfg, rng), make_users(cfg, rng)
    events, _ = make_events(cfg, products, users, rng)
    transitions = events.sort_values(['user_id', 'timestamp']).copy()
    following = transitions.groupby('user_id').event_type.shift(-1)
    after_cart = following[(transitions.event_type == 'cart') & following.notna()]
    assert len(after_cart) > 0
    assert set(after_cart) == {'search' if destination == 'exit' else destination}
    if destination != 'purchase':
        assert not (events.event_type == 'purchase').any()


@pytest.mark.parametrize('reference', [0, -1, float('nan'), float('inf')])
def test_cart_reference_probability_is_validated(tmp_path, reference):
    cfg = load_config()
    cfg['simulator']['cart_reference_cvr'] = reference
    path = tmp_path / 'config.yaml'
    path.write_text(yaml.safe_dump(cfg, sort_keys=False))
    with pytest.raises(ValueError, match='cart_reference_cvr'):
        load_config(str(path))
