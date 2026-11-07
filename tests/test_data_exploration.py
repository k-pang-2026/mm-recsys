from __future__ import annotations

import copy
import json

import numpy as np
import pandas as pd
import pytest

from dashboard.assets import catalog, deployment
from src.common.artifacts import write_json
from src.common.config import load_config
from src.evaluation.data_audit import audit
from src.simulator.catalog import make_catalog
from src.simulator.events import make_events
from src.simulator.generate import generate
from src.simulator.users import make_users


def test_persona_brand_override_changes_only_configured_behavior():
    cfg = load_config()
    cfg['simulator'].update(n_products=1000, n_users=120, n_events=12000)
    rng = np.random.default_rng(42)
    products = make_catalog(cfg, rng)
    users = make_users(cfg, rng)
    users['persona'] = 'brand_loyal'
    concentrations = []
    for probability in (0., 1.):
        local = copy.deepcopy(cfg)
        local['simulator']['personas']['brand_loyal']['preferred_brand_probability'] = probability
        events, _ = make_events(local, products, users, np.random.default_rng(42))
        purchases = events[events.event_type=='purchase'].merge(products[['product_id','brand']], on='product_id')
        counts = purchases.groupby(['user_id', 'brand']).size()
        concentrations.append((counts.groupby('user_id').max()/counts.groupby('user_id').sum()).mean())
    assert concentrations[1] > concentrations[0] + .1
    assert 'preferred_brand' not in users.columns


def test_audit_purchase_ledger_and_stale_dashboard_identity(tmp_path):
    cfg = load_config()
    cfg['simulator'].update(n_products=450, n_users=120, n_events=6000)
    cfg['paths'].update(data_dir=str(tmp_path/'data'), results_dir=str(tmp_path/'results'))
    manifest = generate(cfg)
    report = audit(cfg)
    ledger = pd.read_parquet(report['purchase_ledger'])
    events = pd.read_parquet(tmp_path/'data/events.parquet')
    assert len(ledger) == (events.event_type=='purchase').sum()
    assert ledger.price_percentile.between(0, 1).all()
    assert ledger.views_since_previous_purchase.ge(0).all()
    assert sum(r['users'] for r in report['personas']) == 120
    assert report['excluded']['ledger_rows_dropped'] == 0
    assert report['checks']['references'] and report['checks']['hashes']
    assert len(catalog(cfg['paths']['data_dir'], manifest['generation_fingerprint'])) == 450
    with pytest.raises(ValueError, match='fingerprint'):
        catalog(cfg['paths']['data_dir'], 'wrong-version')
    write_json(tmp_path/'results/deployment.json', dict(data_dir=cfg['paths']['data_dir'], data_fingerprint='old'))
    with pytest.raises(ValueError, match='identity'):
        deployment(tmp_path/'results')


def test_yaml_persona_ratios_and_taxonomy_change_generated_assets(tmp_path, monkeypatch):
    import yaml
    cfg = load_config()
    cfg['scales']['dev'] = dict(n_products=450, n_users=120, n_events=4000)
    cfg['simulator']['personas']['trendsetter']['ratio'] = .25
    cfg['simulator']['personas']['pragmatist']['ratio'] = .10
    cfg['simulator']['taxonomy']['tops']['shirts'] = ['custom shirt']
    path = tmp_path/'config.yaml'
    path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding='utf-8')
    monkeypatch.setenv('SCALE', 'dev')
    changed = load_config(str(path))
    rng = np.random.default_rng(42)
    products = make_catalog(changed, rng)
    users = make_users(changed, rng)
    assert 'custom shirt' in set(products.category_l3)
    assert users.persona.value_counts()['trendsetter'] == 30
    assert users.persona.value_counts()['pragmatist'] == 12
