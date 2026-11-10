"""Opt-in CT worker calls reload through the API's shared loopback namespace."""
from __future__ import annotations

import os
import sys

from docker.http import wait_ready
from docker.runtime import runtime_config, config_path
from src.common.console import log, run_cli


def main() -> None:
    api = 'http://127.0.0.1:8000'
    log('CT', '준비', f'API 준비 대기 / URL={api}')
    wait_ready(api, float(os.getenv('READY_TIMEOUT_SECONDS', '21600')))
    os.environ['CONFIG_PATH'] = str(config_path(runtime_config()))
    log('CT', '시작', 'API 준비 완료 / 모니터링 및 임계치 기반 재학습 작업자를 시작합니다.', status='성공')
    os.execv(sys.executable, [sys.executable, 'scripts/demo.py', 'ct', '--watch', '--train',
                             '--reload-url', api])


if __name__ == '__main__':
    run_cli(main, 'CT 작업자', 'API /ready·모델 준비 로그·루프백 연결을 확인하세요.')
