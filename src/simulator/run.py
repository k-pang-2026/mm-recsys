"""Continuous, chronological event replay; generated outcomes are not labeled as live user traffic."""
from __future__ import annotations

import argparse
import time
from pathlib import Path
import pandas as pd
from src.common.config import load_config
from src.simulator.generate import generate


def main() -> None:
    parser=argparse.ArgumentParser();parser.add_argument('--interval',type=float,default=5)
    parser.add_argument('--batch-size',type=int,default=100);parser.add_argument('--once',action='store_true')
    args=parser.parse_args();cfg=load_config();generate(cfg)
    root=Path(cfg['paths']['data_dir']);stream=root/'stream';stream.mkdir(exist_ok=True)
    events=pd.read_parquet(root/'events.parquet');cursor=stream/'cursor.txt'
    offset=int(cursor.read_text()) if cursor.exists() else 0
    while offset<len(events):
        batch=events.iloc[offset:offset+args.batch_size]
        name=stream/f'events-{offset:09d}.parquet'
        if not name.exists():batch.to_parquet(name,index=False)
        offset+=len(batch);temporary=cursor.with_suffix('.tmp');temporary.write_text(str(offset));temporary.replace(cursor)
        print(f'event replay: {offset}/{len(events)}',flush=True)
        if args.once:break
        time.sleep(args.interval)
    # B6 connects these chunks to Redis; no repeated emission of the same event IDs.


if __name__=='__main__':main()
