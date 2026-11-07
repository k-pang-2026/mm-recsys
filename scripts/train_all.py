"""Explicit isolated Two Tower/DeepFM/session training interface for A B10 and CT."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.common.console import log, emit_json, run_cli
from src.common.config import load_config
from src.ct.training import train_all


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--work-dir', required=True, type=Path)
    parser.add_argument('--data-dir', type=Path)
    args = parser.parse_args(); cfg = load_config()
    if args.data_dir:
        cfg['paths']['data_dir'] = str(args.data_dir)
    reports, path = train_all(cfg, args.work_dir)
    log('모델', '학습', f'호환 번들 준비 완료: {path} / valid 검증만 수행 / 자동 승격 없음', status='성공')
    emit_json(dict(bundle=str(path), reports=reports))
    return 0


if __name__ == '__main__':
    raise SystemExit(run_cli(main, '모델 학습', '데이터·설정·번들 경로와 원본 오류를 확인하세요.'))
