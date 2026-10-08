from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path
import numpy as np
from src.common.artifacts import file_hash,fingerprint,write_json
from src.common.config import load_config
from src.simulator.catalog import make_catalog,write_images
from src.simulator.users import make_users
from src.simulator.events import make_events
from src.simulator.split import chronological_split

GENERATOR_VERSION='4.0.0'


def generate(cfg: dict, data_dir: Path | None = None) -> dict:
    data_dir=data_dir or Path(cfg['paths']['data_dir'])
    expected=fingerprint({'seed':cfg['seed'],'simulator':cfg['simulator'],'split':cfg['split'],'generator':GENERATOR_VERSION})
    manifest_path=data_dir/'split_manifest.json'
    if manifest_path.exists():
        manifest=json.loads(manifest_path.read_text())
        if manifest.get('generation_fingerprint')!=expected:
            raise ValueError('Existing dataset has a different fingerprint; select a new data_dir/version, do not overwrite frozen data')
        for name,digest in manifest['file_hashes'].items():
            if not (data_dir/name).is_file() or file_hash(data_dir/name)!=digest:
                raise ValueError(f'Incomplete or modified dataset: {name}')
        images=data_dir/'images'
        if len(list(images.glob('*.jpg')))!=cfg['simulator']['n_products']:
            raise ValueError('Incomplete product image set; restore/regenerate in a new data_dir')
        for name,digest in json.loads((data_dir/'image_manifest.json').read_text()).items():
            if file_hash(data_dir/name)!=digest:
                raise ValueError(f'Incomplete or modified product image: {name}')
        return manifest
    data_dir.mkdir(parents=True,exist_ok=True)
    temporary=Path(tempfile.mkdtemp(prefix='.generation-',dir=data_dir.parent))
    try:
        rng=np.random.default_rng(cfg['seed'])
        products=make_catalog(cfg,rng);users=make_users(cfg,rng)
        events,impressions=make_events(cfg,products,users,rng)
        write_images(products,cfg,temporary)
        write_json(temporary/'image_manifest.json',dict(zip(products.image_path,products.image_sha256)))
        (temporary/'split').mkdir()
        for name,frame in [('products',products),('users',users),('events',events),('impressions',impressions)]:
            frame.to_parquet(temporary/f'{name}.parquet',index=False)
        splits=chronological_split(events,cfg['split'])
        for name,frame in splits.items():frame.to_parquet(temporary/f'split/{name}.parquet',index=False)
        files=['products.parquet','users.parquet','events.parquet','impressions.parquet','image_manifest.json',*[f'split/{name}.parquet' for name in splits]]
        manifest={'generator_version':GENERATOR_VERSION,'generation_fingerprint':expected,'scale':cfg['scale'],'seed':cfg['seed'],
                  'reference_time':cfg['simulator']['reference_time'],
                  'counts':{'products':len(products),'users':len(users),'events':len(events),'impressions':len(impressions)},
                  'split_counts':{name:len(frame) for name,frame in splits.items()},
                  'boundaries':{name:{'start':str(frame.timestamp.min()),'end':str(frame.timestamp.max())} for name,frame in splits.items()},
                  'file_hashes':{name:file_hash(temporary/name) for name in files},'cutoff_policy':'fixed_origin',
                  'images':'synthetic category silhouettes; observed attributes only; no unique-ID semantics'}
        # Manifest is written last. Multiple writers fail rather than overwrite each other's dataset.
        for name in ['images','split',*files[:5]]:
            source=temporary/name;target=data_dir/name
            if target.exists():raise ValueError(f'Unregistered existing data prevents overwrite: {target}')
            source.rename(target)
        write_json(manifest_path,manifest)
        return manifest
    finally:
        shutil.rmtree(temporary,ignore_errors=True)


def main() -> None:
    parser=argparse.ArgumentParser();parser.add_argument('--data-dir',type=Path)
    args=parser.parse_args()
    print(json.dumps(generate(load_config(),args.data_dir),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
