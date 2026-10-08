from __future__ import annotations
import copy
import os
from pathlib import Path
from typing import Any
import yaml

def load_config(path: str | None = None) -> dict[str, Any]:
    p = Path(path or os.getenv("CONFIG_PATH", "config.yaml"))
    with p.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ValueError("config must be a mapping")
    cfg = copy.deepcopy(raw)
    def merge(base: dict, extra: dict) -> None:
        for key, value in extra.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                merge(base[key], value)
            else:
                base[key] = copy.deepcopy(value)
    for section in ("search", "recommend", "serving"):
        overlay = p.parent / "config" / f"{section}.yaml"
        if overlay.exists():
            value = yaml.safe_load(overlay.read_text(encoding="utf-8")) or {}
            if set(value) - {section}:
                raise ValueError(f"{overlay} may only configure {section}")
            merge(cfg, value)
    scale = os.getenv("SCALE") or cfg.get("scale", "dev")
    if scale not in cfg.get("scales", {}):
        raise ValueError(f"Unknown SCALE={scale}; configure scales.dev/full (B0)")
    cfg["scale"] = scale
    cfg["simulator"].update(cfg["scales"][scale])
    cfg['paths'].update(cfg['paths'].get('by_scale',{}).get(scale,{}))
    host, port = os.getenv("REDIS_HOST"), os.getenv("REDIS_PORT")
    if host:
        cfg["redis"]["host"] = host
    if port:
        cfg["redis"]["port"] = int(port)
    if not 1 <= int(cfg["redis"]["port"]) <= 65535:
        raise ValueError("REDIS_PORT must be 1..65535")
    if any(not isinstance(cfg["simulator"][key], int) or cfg["simulator"][key] <= 0
           for key in ("n_products", "n_users", "n_events")):
        raise ValueError("simulator counts must be positive integers")
    fractions = [float(cfg["split"][k]) for k in ("train", "valid", "test")]
    if any(x <= 0 for x in fractions) or abs(sum(fractions) - 1.0) > 1e-9:
        raise ValueError("split fractions must sum to 1")
    sim = cfg["simulator"]
    ratios = [float(value["ratio"]) for value in sim["personas"].values()]
    if len(ratios) < 6 or any(x <= 0 for x in ratios) or abs(sum(ratios)-1) > 1e-9:
        raise ValueError("configure six positive persona ratios summing to 1")
    if not 0 <= sim["new_item_ratio"] < 1 or not 0 <= sim["cold_user_ratio"] < 1:
        raise ValueError("new-item/cold-user ratios must be in [0,1)")
    if sim["impressions_per_view"] < 2 or sim["impressions_per_view"] > sim["n_products"]:
        raise ValueError("impressions_per_view must be 2..n_products")
    if int(sim['n_products']*(1-sim['new_item_ratio'])) < sim['impressions_per_view']:
        raise ValueError('initial catalog must contain enough distinct exposed items')
    choice=sim['choice_model']
    if any(not 0 <= choice[key] <= 1 for key in ('uniform_noise','preferred_leaf_probability','preferred_brand_probability')):
        raise ValueError('choice probabilities must be in [0,1]')
    if choice['zipf_alpha'] < 0 or sim['image_size'] < 16 or sim['image_variants'] < 1:
        raise ValueError('invalid demand/image parameters')
    for spec in sim['personas'].values():
        if len(spec['category_preferences']) != len(sim['taxonomy']) or abs(sum(spec['category_preferences'])-1)>1e-9:
            raise ValueError('persona category preferences must match taxonomy and sum to 1')
    for transitions in sim["transitions"].values():
        values = [float(x) for x in transitions.values()]
        if any(x < 0 for x in values) or abs(sum(values)-1) > 1e-9:
            raise ValueError("Markov transition probabilities must sum to 1")
    return cfg
