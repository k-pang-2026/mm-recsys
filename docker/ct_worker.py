"""Opt-in CT worker calls reload through the API's shared loopback namespace."""
from __future__ import annotations

import os
import sys

from docker.http import wait_ready
from docker.runtime import runtime_config, config_path


def main() -> None:
    api = 'http://127.0.0.1:8000'
    wait_ready(api, float(os.getenv('READY_TIMEOUT_SECONDS', '21600')))
    os.environ['CONFIG_PATH'] = str(config_path(runtime_config()))
    os.execv(sys.executable, [sys.executable, '-m', 'src.ct.retrain_trigger', '--watch', '--train',
                             '--reload-url', api])


if __name__ == '__main__':
    main()
