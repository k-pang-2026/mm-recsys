"""Explicit isolated Two Tower/DeepFM/session training interface for A B10 and CT."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.common.config import load_config
from src.ct.training import train_all


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--data-dir', type=Path)
    args = parser.parse_args(); cfg = load_config()
    if args.data_dir:
        cfg['paths']['data_dir'] = str(args.data_dir)
    _, path = train_all(cfg, args.work_dir)
    print(f'Complete compatible bundle: {path}; validation only; not automatically promoted')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
