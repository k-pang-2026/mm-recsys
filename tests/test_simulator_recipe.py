"""A sorted YAML roundtrip must never share identity with a different simulation."""
from __future__ import annotations

import copy
import numpy as np
import yaml

from src.common.artifacts import fingerprint
from src.common.config import load_config
from src.simulator.catalog import make_catalog
from src.simulator.generate import generation_identity


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
