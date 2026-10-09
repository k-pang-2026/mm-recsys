"""Consume simulator parquet chunks without editing the shared simulator."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import pandas as pd

from src.common.artifacts import file_hash, write_json
from src.common.config import load_config
from src.common.schemas import EventRequest, FeedbackRequest
from src.serving.feature_store import RedisFeatureStore, create_feature_store


def replay_stream(cfg: dict, store: RedisFeatureStore) -> dict:
    root = Path(cfg["paths"]["data_dir"])
    stream = root / "stream"
    stream.mkdir(parents=True, exist_ok=True)
    # A namespace has its own checkpoint; a fresh Redis should use a fresh namespace.
    checkpoint = stream / (store.key("checkpoint", store.namespace).replace(":", "-") + ".json")
    manifest = json.loads((root / "split_manifest.json").read_text())
    identity = manifest["generation_fingerprint"]
    saved = json.loads(checkpoint.read_text()) if checkpoint.exists() else {
        "data_fingerprint": identity, "chunks": {}}
    if saved["data_fingerprint"] != identity:
        raise ValueError("stream data fingerprint changed; select a fresh data path/namespace")
    categories = pd.read_parquet(root / "products.parquet", columns=["product_id", "category_l1"])
    category = dict(zip(categories.product_id, categories.category_l1))
    count = 0
    for path in sorted(stream.glob("events-*.parquet")):
        digest = file_hash(path)
        if path.name in saved["chunks"]:
            if saved["chunks"][path.name] != digest:
                raise ValueError(f"previously consumed stream chunk changed: {path.name}")
            continue
        for row in pd.read_parquet(path).to_dict("records"):
            if row["event_type"] not in ("view", "cart", "purchase") or pd.isna(row["product_id"]):
                continue
            event = EventRequest(event_id=str(row["event_id"]), user_id=str(row["user_id"]),
                                 product_id=str(row["product_id"]), event_type=row["event_type"],
                                 session_id=str(row["session_id"]),
                                 category=category.get(row["product_id"]))
            store.append_event(event)
            if not store.available:
                raise ConnectionError("Redis event write failed; chunk checkpoint was preserved")
            store.update_reward(FeedbackRequest(**event.model_dump()))
            if not store.available:
                raise ConnectionError("Redis reward write failed; chunk checkpoint was preserved")
            count += 1
        saved["chunks"][path.name] = digest
        write_json(checkpoint, saved)
    return {"events_processed": count, "chunks_completed": len(saved["chunks"]),
            "data_fingerprint": identity}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=5)
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("interval must be positive")
    cfg = load_config()
    store = create_feature_store(cfg)
    if not isinstance(store, RedisFeatureStore):
        raise ValueError("stream replay requires Redis")
    try:
        while True:
            print(json.dumps(replay_stream(cfg, store)), flush=True)
            if args.once:
                break
            time.sleep(args.interval)
    finally:
        store.close()


if __name__ == "__main__":
    main()
