"""Freeze independent queries before evaluation. Labels never enter the searcher."""
from __future__ import annotations

import argparse
from io import BytesIO
import json
from pathlib import Path
import numpy as np
import pandas as pd
from PIL import Image, ImageEnhance

from src.common.artifacts import file_hash, fingerprint, write_json
from src.common.config import load_config
from src.simulator.catalog import render_product
from src.search.text import ALIASES, PREPROCESS_VERSION

QUERY_VERSION = 'observable-query-v1'
AUGMENTATION = {'rotation_degrees': 6, 'translate_pixels': 4, 'brightness': [0.9, 1.1],
                'contrast': [0.9, 1.1], 'encoding': 'PNG', 'version': 1}


def freeze_queries(cfg: dict) -> Path:
    root = Path(cfg['paths']['data_dir']); catalog = root/'products.parquet'
    dataset = json.loads((root/'split_manifest.json').read_text())
    if file_hash(catalog) != dataset['file_hashes']['products.parquet']:
        raise ValueError('query catalog differs from frozen dataset')
    spec = cfg['search']['evaluation']
    if spec['version'] != QUERY_VERSION:
        raise ValueError('unsupported query evaluation version')
    identity = {'version': QUERY_VERSION, 'scale': cfg['scale'], 'data_fingerprint': dataset['generation_fingerprint'],
                'catalog_sha256': file_hash(catalog), 'preprocessing': PREPROCESS_VERSION,
                'alias_fingerprint': fingerprint(ALIASES), 'queries_per_mode': int(spec['queries_per_mode']),
                'seeds': {'valid': int(spec['valid_seed']), 'test': int(spec['test_seed'])},
                'text_style_probability': float(spec['text_style_probability']),
                'korean_probability': float(spec['korean_probability']), 'augmentation': AUGMENTATION,
                'relevance': {'text': ['category_l3', 'color', 'style_if_explicit'],
                              'image': ['category_l1', 'color'], 'hybrid': ['category_l3', 'color', 'style_if_explicit']},
                'cutoffs': {'valid': dataset['boundaries']['train']['end'],
                            'test': dataset['boundaries']['valid']['end']}}
    if identity['seeds']['valid'] == identity['seeds']['test']:
        raise ValueError('valid/test query seeds must differ')
    key = fingerprint(identity); folder = root/'search_queries'/key; folder.mkdir(parents=True, exist_ok=True)
    manifest_path = folder/'manifest.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest['identity'] != identity or manifest.get('status') != 'COMPLETE':
            raise ValueError('incompatible frozen queries')
        for name, digest in manifest['files'].items():
            if file_hash(folder/name) != digest:
                raise ValueError(f'changed frozen query: {name}')
        return folder
    products = pd.read_parquet(catalog).sort_values('product_id', kind='stable')
    catalog_hashes = set(products.image_sha256)
    inverse = {}
    for korean, english in ALIASES.items():
        inverse.setdefault(english, korean)
    files = {}; counts = {}; distinct = {}
    for split, seed in identity['seeds'].items():
        rng = np.random.default_rng(seed); queries = []
        candidates = products[pd.to_datetime(products.created_at, utc=True) <= pd.Timestamp(identity['cutoffs'][split])]
        if candidates.empty:
            raise ValueError('empty cutoff catalog for queries')
        for mode in ('text', 'image', 'hybrid'):
            for i in range(identity['queries_per_mode']):
                row = candidates.iloc[int(rng.integers(len(candidates)))].to_dict()
                attributes = {'color': row['color'], 'category_l1' if mode == 'image' else 'category_l3':
                              row['category_l1'] if mode == 'image' else row['category_l3']}
                raw_text = None; image_path = None
                if mode != 'image':
                    tokens = [row['color']]
                    if rng.random() < identity['text_style_probability']:
                        tokens.append(row['style']); attributes['style'] = row['style']
                    tokens.append(row['category_l3'])
                    if rng.random() < identity['korean_probability']:
                        tokens = [inverse.get(token, token) for token in tokens]
                    raw_text = ' '.join(tokens)
                if mode != 'text':
                    image = render_product(row, cfg, variant=int(rng.integers(100, 10000)))
                    image = ImageEnhance.Brightness(image).enhance(float(rng.uniform(0.9, 1.1)))
                    image = ImageEnhance.Contrast(image).enhance(float(rng.uniform(0.9, 1.1)))
                    image = image.rotate(float(rng.uniform(-6, 6)), resample=Image.Resampling.BICUBIC,
                                         translate=tuple(int(v) for v in rng.integers(-4, 5, size=2)), fillcolor='#f4f1ed')
                    image_path = f'{split}/{mode}-{i:04d}.png'; path = folder/image_path
                    path.parent.mkdir(exist_ok=True); image.save(path)
                    digest = file_hash(path)
                    if digest in catalog_hashes:
                        raise ValueError('quality query is an exact catalog image duplicate')
                    files[image_path] = digest
                queries.append({'query_id': f'{split}-{mode}-{i:04d}', 'mode': mode, 'query_text': raw_text,
                                'query_image_path': image_path, 'relevance_attributes': attributes})
        name = f'{split}.json'; write_json(folder/name, queries); files[name] = file_hash(folder/name)
        counts[split] = {mode: sum(q['mode'] == mode for q in queries) for mode in ('text', 'image', 'hybrid')}
        distinct[split] = len({fingerprint(q['relevance_attributes']) for q in queries})
    write_json(manifest_path, {'status': 'COMPLETE', 'fingerprint': key, 'identity': identity,
                             'counts': counts, 'distinct_attribute_sets': distinct, 'files': files})
    return folder


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    cfg = load_config(); folder = freeze_queries(cfg)
    manifest = json.loads((folder/'manifest.json').read_text())
    summary = {'scope': 'frozen before quality evaluation', 'path': str(folder),
               'manifest_sha256': file_hash(folder/'manifest.json'),
               'fingerprint': manifest['fingerprint'], 'identity': manifest['identity'], 'counts': manifest['counts']}
    write_json(Path(f'docs/results/search_queries_{cfg["scale"]}.json'), summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
