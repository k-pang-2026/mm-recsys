from __future__ import annotations

import json
import hashlib
from pathlib import Path
import numpy as np
import pandas as pd
from PIL import Image, ImageDraw


def leaves(cfg: dict) -> list[tuple[str, str, str]]:
    return [(l1, l2, l3) for l1, mids in cfg['simulator']['taxonomy'].items()
            for l2, values in mids.items() for l3 in values]


def render_product(row: dict, cfg: dict, variant: int = 0) -> Image.Image:
    size = cfg['simulator']['image_size']
    image = Image.new('RGB', (size, size), '#f4f1ed')
    draw = ImageDraw.Draw(image)
    color = cfg['simulator']['colors'][row['color']]
    # Category-specific silhouettes, kept away from crop edges; no text/ID/brand watermark.
    x = size / 224
    def points(values):
        return [(int(a*x), int(b*x)) for a,b in values]
    kind = row['category_l1']
    if kind in ('tops', 'outerwear'):
        draw.polygon(points([(76,40),(94,50),(130,50),(148,40),(184,80),(163,108),
                             (148,94),(148,190),(76,190),(76,94),(60,108),(40,80)]), fill=color)
        draw.ellipse((94*x,35*x,130*x,61*x),fill='#f4f1ed')
        if kind == 'outerwear':
            draw.line(points([(112,58),(112,190)]),fill='#999999',width=max(1,int(3*x)))
    elif kind == 'bottoms':
        if 'skirt' in row['category_l3']:
            draw.polygon(points([(80,48),(144,48),(176,185),(48,185)]),fill=color)
        else:
            draw.polygon(points([(73,44),(151,44),(158,190),(124,190),(112,112),(100,190),(66,190)]),fill=color)
    elif kind == 'footwear':
        draw.polygon(points([(53,115),(103,105),(126,140),(173,155),(183,179),(48,179)]),fill=color)
        draw.line(points([(50,180),(181,180)]),fill='#dddddd',width=max(1,int(8*x)))
        for j in range(4):
            draw.line(points([(105+j*8,133+j*3),(127+j*8,131+j*3)]),fill='#cccccc',width=max(1,int(2*x)))
    elif row['category_l2'] == 'bags':
        draw.rounded_rectangle((64*x,86*x,160*x,184*x),radius=12*x,fill=color)
        draw.arc((83*x,49*x,141*x,125*x),180,360,fill=color,width=max(1,int(9*x)))
    elif row['category_l2'] == 'headwear':
        draw.pieslice((62*x,62*x,162*x,168*x),180,360,fill=color)
        draw.ellipse((45*x,113*x,178*x,139*x),fill=color)
    else:
        draw.polygon(points([(70,54),(96,57),(154,179),(121,186)]),fill=color)
    if variant % 3 == 1:
        draw.line(points([(85,95),(141,95)]), fill='#999999',width=max(1,int(2*x)))
    if row['style'] == 'oversized':
        image = image.resize((size-8,size-8)).resize((size,size))
    return image


def make_catalog(cfg: dict, rng: np.random.Generator) -> pd.DataFrame:
    sim = cfg['simulator']; n = sim['n_products']; taxonomy = leaves(cfg)
    leaf_ids = np.arange(n) % len(taxonomy)
    rng.shuffle(leaf_ids)
    brands, colors, styles = sim['brands'], list(sim['colors']), sim['styles']
    brand_ids = rng.integers(len(brands),size=n)
    color_ids = rng.integers(len(colors),size=n)
    style_ids = rng.integers(len(styles),size=n)
    ref = pd.Timestamp(sim['reference_time'])
    created = ref - pd.to_timedelta(rng.integers(35,120,size=n),unit='D')
    new = rng.choice(n,size=int(n*sim['new_item_ratio']),replace=False)
    created = pd.Series(created)
    created.iloc[new] = ref-pd.to_timedelta(rng.integers(0,7,size=len(new)),unit='D')
    rows=[]
    for i in range(n):
        l1,l2,l3 = taxonomy[leaf_ids[i]]
        low,high = sim['category_price_ranges'][l1]
        price = int(rng.uniform(low,high)//1000*1000)
        color,brand,style=colors[color_ids[i]],brands[brand_ids[i]],styles[style_ids[i]]
        rows.append({'product_id':f'P{i+1:06d}','name':f'{color} {style} {l3}',
                     'category_l1':l1,'category_l2':l2,'category_l3':l3,
                     'brand':brand,'color':color,'style':style,
                     'attributes':json.dumps({'style':style},sort_keys=True),
                     'price':price,'created_at':created.iloc[i],
                     'image_path':f'images/P{i+1:06d}.jpg',
                     'description_en':f'a photo of a {color} {style} {l3}'})
    return pd.DataFrame(rows)


def write_images(products: pd.DataFrame, cfg: dict, data_dir: Path) -> None:
    folder=data_dir/'images';folder.mkdir(parents=True,exist_ok=True)
    hashes=[]
    for i,row in enumerate(products.to_dict('records')):
        path=data_dir/row['image_path']
        render_product(row,cfg,i%cfg['simulator']['image_variants']).save(path,quality=85)
        hashes.append(hashlib.sha256(path.read_bytes()).hexdigest())
    products['image_sha256']=hashes
    products['visual_group']=hashes
