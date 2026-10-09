"""Serial Redis feature latency, with execution and dataset evidence."""
from __future__ import annotations

import argparse
import json
import os
import platform
import time
import uuid
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import redis

from src.common.artifacts import fingerprint, write_json
from src.common.config import load_config
from src.common.schemas import EventRequest
from src.serving.feature_store import RedisFeatureStore, create_feature_store


def benchmark(cfg: dict, store: RedisFeatureStore) -> dict:
    info = cast(dict[str, Any], store.client.info("server"))
    users = pd.read_parquet(Path(cfg["paths"]["data_dir"]) / "users.parquet", columns=["user_id"])
    ids = users.user_id.astype(str).tolist()
    if not ids:
        raise ValueError("benchmark requires generated users")
    warmups = int(cfg["benchmark"]["warmup"])
    requests = int(cfg["benchmark"]["requests"])
    if warmups < 10 or requests < 100 or cfg["benchmark"]["concurrency"] != 1:
        raise ValueError("acceptance requires >=10 warmups, >=100 serial requests")
    sample_ids = ids[:min(requests, len(ids))]
    products = pd.read_parquet(Path(cfg["paths"]["data_dir"]) / "products.parquet",
                               columns=["product_id"]).product_id.astype(str).tolist()
    if not products:
        raise ValueError("benchmark requires generated products")
    # Fill a disposable namespace rather than injecting synthetic events into live sessions.
    bench = RedisFeatureStore(store.client, namespace=store.namespace + ":bench:" + uuid.uuid4().hex,
                              history_limit=store.history_limit, session_ttl=store.session_ttl,
                              feedback_ttl=store.feedback_ttl)
    timings = []
    profile_hits = 0
    try:
        bench.batch_load_profiles({user_id: store.get_features(user_id).profile for user_id in sample_ids})
        for user_id in sample_ids:
            for position in range(store.history_limit):
                if not bench.append_event(EventRequest(
                        event_id=f"{user_id}:{position}", user_id=user_id,
                        product_id=products[position % len(products)], event_type="view",
                        session_id="benchmark", category="benchmark")):
                    raise ConnectionError("failed to prepare benchmark histories")
        for i in range(warmups + requests):
            start = time.perf_counter()
            features = bench.get_features(sample_ids[i % len(sample_ids)])
            elapsed = (time.perf_counter() - start) * 1000
            if not bench.available:
                raise ConnectionError("fallback requests cannot establish Redis latency")
            if not features.profile or len(features.recent_clicks) != store.history_limit:
                raise ValueError("benchmark requires warmed profiles and capped histories")
            if i >= warmups:
                timings.append(elapsed)
                profile_hits += int(bool(features.profile))
    finally:
        keys = list(store.client.scan_iter(match=bench.namespace + ":*"))
        if keys:
            store.client.delete(*keys)
    quantiles = np.percentile(timings, [50, 95, 99])
    manifest = json.loads((Path(cfg["paths"]["data_dir"]) / "split_manifest.json").read_text())
    target = cfg["targets"]["feature_p95_ms"]
    return {
        "status": "PASS" if quantiles[1] <= target else "FAIL", "scale": cfg["scale"],
        "acceptance": "UNMEASURED", "target_p95_ms": target,
        "warmup": warmups, "requests": requests, "concurrency": 1,
        "latency_ms": dict(zip(("p50", "p95", "p99"), map(float, quantiles))),
        "samples_ms": timings, "profile_hits": profile_hits, "history_state": "synthetic capped histories", "history_limit": store.history_limit,
        "sample_users": len(sample_ids),
        "data_fingerprint": manifest["generation_fingerprint"],
        "config_fingerprint": fingerprint(cfg),
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
                        "cpu": platform.processor(), "logical_cpus": os.cpu_count(),
                        "ram_bytes": _ram_bytes(), "gpu_used": False, "docker": "UNMEASURED",
                        "redis_version": info["redis_version"], "redis_py": redis.__version__,
                        "redis_host": cfg["redis"]["host"], "redis_port": cfg["redis"]["port"],
                        "redis_maxmemory": store.client.config_get("maxmemory"),
                        "redis_eviction": store.client.config_get("maxmemory-policy")}}


def _ram_bytes() -> int | None:
    if platform.system() == "Windows":
        import ctypes
        class Memory(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                        *[(name, ctypes.c_ulonglong) for name in (
                            "total_phys", "avail_phys", "total_page", "avail_page",
                            "total_virtual", "avail_virtual", "avail_extended")]]
        data = Memory()
        data.length = ctypes.sizeof(data)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(data)):
            return int(data.total_phys)
        return None
    try:
        sysconf = getattr(os, "sysconf")
        return sysconf("SC_PAGE_SIZE") * sysconf("SC_PHYS_PAGES")
    except (AttributeError, ValueError, OSError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    cfg = load_config()
    store = create_feature_store(cfg)
    if not isinstance(store, RedisFeatureStore):
        raise ValueError("latency benchmark requires Redis")
    try:
        result = benchmark(cfg, store)
        destination = args.output or Path(f"docs/results/latency/feature_{cfg['scale']}.json")
        write_json(destination, result)
        print(json.dumps({key: value for key, value in result.items() if key != "samples_ms"}, indent=2))
        if result["status"] != "PASS":
            raise SystemExit(1)
    finally:
        store.close()


if __name__ == "__main__":
    main()
