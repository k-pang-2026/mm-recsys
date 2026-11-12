"""Load observable user profiles; replay is an explicit serving-only operation."""
from __future__ import annotations

from src.common.console import log, run_cli

import argparse
import json
from pathlib import Path

import pandas as pd

from src.common.config import load_config
from src.serving.feature_store import RedisFeatureStore, create_feature_store


def warmup(cfg: dict, store: RedisFeatureStore) -> dict:
    store.client.ping()  # Warmup must fail visibly if Redis is unavailable.
    users = pd.read_parquet(Path(cfg["paths"]["data_dir"]) / "users.parquet")
    columns = [name for name in ("age_group", "gender", "signup_at") if name in users]
    profiles = {str(row["user_id"]): {name: str(row[name]) for name in columns}
                for row in users.to_dict("records")}
    store.batch_load_profiles(profiles)
    return {"status": "PASS", "scale": cfg["scale"], "profile_count": len(profiles),
            "batch_size": 1000, "history_loaded": False, "namespace": store.namespace}


def main() -> None:
    parser = argparse.ArgumentParser(description='Redis 피처 준비')
    parser.add_argument("--replay-stream", action="store_true")
    args = parser.parse_args()
    cfg = load_config()
    store = create_feature_store(cfg)
    if not isinstance(store, RedisFeatureStore):
        raise ValueError("warmup requires serving.feature_store=redis")
    try:
        result = warmup(cfg, store)
        if args.replay_stream:
            from src.serving.stream_features import replay_stream
            result["stream"] = replay_stream(cfg, store)
        log('Redis 피처 준비', '결과', f"규모={result.get('scale', '설정 참조')} / 판정={result.get('status', '원본 JSON 참조')}", status='완료')
        print(json.dumps(result, indent=2))
    finally:
        store.close()


if __name__ == "__main__":
    run_cli(main, 'Redis 피처 준비', '설정·데이터·모델·Redis 상태와 위 원본 오류를 확인한 뒤 같은 명령을 다시 실행하세요.')
