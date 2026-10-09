import json
from pathlib import Path
import threading
import numpy as np
import pandas as pd
import pytest

from src.common.artifacts import file_hash, write_json
from src.common.config import load_config
from src.simulator.catalog import make_catalog, write_images
from src.search.queries import freeze_queries
from src.search.searcher import Searcher
from src.search.eval_search import score_rankings, evaluate


def test_frozen_queries_are_independent_augmented_and_immutable(tmp_path):
    cfg = load_config(); cfg['paths']['data_dir'] = str(tmp_path)
    cfg['simulator']['n_products'] = 120; cfg['simulator']['image_size'] = 32
    cfg['search']['evaluation']['queries_per_mode'] = 3
    products = make_catalog(cfg, np.random.default_rng(cfg['seed']))
    write_images(products, cfg, tmp_path); products.to_parquet(tmp_path/'products.parquet', index=False)
    write_json(tmp_path/'split_manifest.json', {'generation_fingerprint': 'fixture-frozen-data',
        'file_hashes': {'products.parquet': file_hash(tmp_path/'products.parquet')},
        'boundaries': {'train': {'end': '2025-12-25T00:00:00Z'}, 'valid': {'end': '2025-12-28T00:00:00Z'}}})
    folder = freeze_queries(cfg); digest = file_hash(folder/'manifest.json')
    assert freeze_queries(cfg) == folder and file_hash(folder/'manifest.json') == digest
    valid = json.loads((folder/'valid.json').read_text()); test = json.loads((folder/'test.json').read_text())
    assert len(valid) == len(test) == 9 and valid != test
    catalog_hashes = set(products.image_sha256)
    for query in valid+test:
        if query['query_image_path']:
            assert file_hash(folder/query['query_image_path']) not in catalog_hashes
        if query['mode'] == 'image':
            assert set(query['relevance_attributes']) == {'category_l1', 'color'}
    (folder/valid[3]['query_image_path']).write_bytes(b'changed image')
    with pytest.raises(ValueError, match='changed frozen'):
        freeze_queries(cfg)


def test_hybrid_really_uses_both_modalities_with_selected_weights():
    class Encoder:
        def encode_texts(self, values):
            return np.array([[1, 0]], np.float32)
        def encode_images(self, values):
            return np.array([[0, 1]], np.float32)
    searcher = Searcher.__new__(Searcher); searcher.cfg = load_config(); searcher.encoder = Encoder()
    searcher._lock = threading.RLock()
    mode, query = searcher.encode('shirt', object())
    assert mode == 'hybrid' and query[0, 1] > 0
    assert query[0, 0]/query[0, 1] == pytest.approx(3)
    assert searcher.encode('  ', object())[0] == 'image'


def test_multi_relevant_ndcg_and_missing_truth_are_not_redefined():
    result = score_rankings([['A', 'B']], [{'B', 'C'}])
    assert result['mrr'] == 0.5 and 0 < result['ndcg_at_10'] < 1
    with pytest.raises(ValueError, match='empty frozen truth'):
        score_rankings([['A']], [set()])
    with pytest.raises(ValueError, match='only use valid'):
        evaluate(load_config(), 'test', sweep=True)
