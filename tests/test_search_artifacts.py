"""Synthetic fixture encoders only test integrity, not real CLIP quality."""
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from PIL import Image
import pytest

from src.common.artifacts import file_hash, fingerprint, write_json
from src.common.config import load_config
from src.search.build_embeddings import build_embeddings, current_bundle, load_bundle
from src.search.build_index import build_indexes, current_indexes
from src.search.encoder import unit_vectors
from src.search.index import SearchIndex
from src.search.text import ALIASES, PREPROCESS_VERSION
from src.search.locking import writer_lock


class FixtureEncoder:
    dim = 16
    def __init__(self, cfg):
        self.metadata = {'projection_dim': self.dim, 'model': cfg['search']['clip_model'],
                         'model_revision': cfg['search']['clip_revision'], 'fixture': True,
                         'alias_fingerprint': fingerprint(ALIASES), 'preprocess_version': PREPROCESS_VERSION}
        self.text_count = 0; self.image_count = 0; self.fail_after = None
    def encode_texts(self, texts):
        if self.fail_after is not None and self.text_count >= self.fail_after:
            raise RuntimeError('injected interruption')
        self.text_count += len(texts)
        return self._vectors(texts)
    def encode_images(self, paths):
        self.image_count += len(paths)
        return self._vectors([file_hash(path) for path in paths])
    def _vectors(self, values):
        return unit_vectors(np.array([list(hashlib.sha256(str(v).encode()).digest()[:16]) for v in values], np.float32))


@pytest.fixture
def catalog_cfg(tmp_path):
    cfg = load_config(); cfg['paths']['data_dir'] = str(tmp_path/'data'); cfg['paths']['model_dir'] = str(tmp_path/'models')
    cfg['search']['embedding_chunk_size'] = 2
    root = Path(cfg['paths']['data_dir']); root.mkdir()
    rows = []
    for i in range(6):
        path = root/f'image-{i}.png'; Image.new('RGB', (20, 20), 'red' if i%2 else 'blue').save(path)
        rows.append({'product_id': f'P{6-i:02d}', 'description_en': f'a photo of color {i%3} shirt',
                     'image_path': path.name, 'image_sha256': file_hash(path)})
    pd.DataFrame(rows).to_parquet(root/'products.parquet', index=False)
    write_json(root/'split_manifest.json', {'generation_fingerprint': 'fixture-dataset',
              'file_hashes': {'products.parquet': file_hash(root/'products.parquet')}})
    return cfg


def test_content_cache_and_explicit_alignment(catalog_cfg):
    encoder = FixtureEncoder(catalog_cfg); folder = build_embeddings(catalog_cfg, encoder)
    bundle = load_bundle(folder)
    assert bundle['ids'] == ['P01', 'P02', 'P03', 'P04', 'P05', 'P06']
    assert encoder.text_count == 3 and encoder.image_count == 2
    np.testing.assert_array_equal(bundle['text'][0], bundle['text'][3])
    np.testing.assert_array_equal(bundle['image'][0], bundle['image'][2])
    assert build_embeddings(catalog_cfg, encoder) == folder
    assert encoder.text_count == 3


def test_interruption_reuses_only_receipted_chunks(catalog_cfg):
    first = FixtureEncoder(catalog_cfg); first.fail_after = 2
    with pytest.raises(RuntimeError, match='interruption'):
        build_embeddings(catalog_cfg, first)
    base = Path(catalog_cfg['paths']['model_dir'])/'search'
    assert not (base/'embeddings_current.json').exists()
    partial = next((base/'embeddings').glob('.*.partial'))
    # Simulate a crashed second chunk with no receipt: it must be recomputed.
    (partial/'chunks/text-000000002.npy').write_bytes(b'partial array')
    resumed = FixtureEncoder(catalog_cfg)
    folder = build_embeddings(catalog_cfg, resumed)
    assert resumed.text_count == 1 and resumed.image_count == 2
    assert load_bundle(folder)['manifest']['status'] == 'COMPLETE'


def test_corrupted_completed_chunk_blocks_resume(catalog_cfg):
    first = FixtureEncoder(catalog_cfg); first.fail_after = 2
    with pytest.raises(RuntimeError):
        build_embeddings(catalog_cfg, first)
    partial = next((Path(catalog_cfg['paths']['model_dir'])/'search/embeddings').glob('.*.partial'))
    (partial/'chunks/text-000000000.npy').write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='completed chunk'):
        build_embeddings(catalog_cfg, FixtureEncoder(catalog_cfg))


def test_mismatched_resume_identity_is_rejected(catalog_cfg):
    first = FixtureEncoder(catalog_cfg); first.fail_after = 2
    with pytest.raises(RuntimeError):
        build_embeddings(catalog_cfg, first)
    partial = next((Path(catalog_cfg['paths']['model_dir'])/'search/embeddings').glob('.*.partial'))
    write_json(partial/'identity.json', {'wrong': 'model'})
    with pytest.raises(ValueError, match='resume identity'):
        build_embeddings(catalog_cfg, FixtureEncoder(catalog_cfg))


def test_image_and_catalog_hash_mismatches_are_rejected(catalog_cfg):
    root = Path(catalog_cfg['paths']['data_dir']); (root/'image-0.png').write_bytes(b'bad')
    with pytest.raises(ValueError, match='image checksum'):
        build_embeddings(catalog_cfg, FixtureEncoder(catalog_cfg))
    (root/'products.parquet').write_bytes(b'bad')
    with pytest.raises(ValueError, match='catalog differs'):
        build_embeddings(catalog_cfg, FixtureEncoder(catalog_cfg))


def test_final_checksum_and_reordered_mapping_are_rejected(catalog_cfg):
    folder = build_embeddings(catalog_cfg, FixtureEncoder(catalog_cfg))
    manifest = json.loads((folder/'manifest.json').read_text())
    ids = json.loads((folder/'item_ids.json').read_text()); ids.reverse(); write_json(folder/'item_ids.json', ids)
    with pytest.raises(ValueError, match='checksum'):
        load_bundle(folder)
    manifest['files']['item_ids.json'] = file_hash(folder/'item_ids.json'); write_json(folder/'manifest.json', manifest)
    with pytest.raises(ValueError, match='ID order'):
        load_bundle(folder)


def test_index_bundle_parity_and_stale_configuration(catalog_cfg):
    build_embeddings(catalog_cfg, FixtureEncoder(catalog_cfg)); bundle = current_bundle(catalog_cfg)
    folder = build_indexes(catalog_cfg)
    for mode in ('text', 'image', 'hybrid'):
        loaded = SearchIndex.load(folder, mode, bundle['manifest']['fingerprint'])
        assert len(loaded.search(bundle['text'][:1], 10)[0]) == 6
    with pytest.raises(ValueError, match='stale'):
        SearchIndex.load(folder, 'text', 'different-version')
    catalog_cfg['search']['fusion']['text_weight'] = 0.9
    with pytest.raises(ValueError, match='stale index'):
        current_indexes(catalog_cfg)


def test_concurrent_writer_is_blocked_and_lock_can_be_reused(tmp_path):
    if __import__('os').name == 'nt':
        pytest.skip('Windows byte locks are tested through process-level runtime')
    path = tmp_path/'version.lock'
    with writer_lock(path):
        with pytest.raises(ValueError, match='another process'):
            with writer_lock(path):
                pass
    with writer_lock(path):
        pass
