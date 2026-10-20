"""Wait for the model API, then announce the dashboard only after HTTP readiness."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.request

from docker.http import wait_ready


def wait_dashboard(process: subprocess.Popen, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f'대시보드가 준비 전에 종료되었습니다: exit {process.returncode}')
        try:
            with opener.open('http://127.0.0.1:8501/_stcore/health', timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(min(.5, max(0, deadline - time.monotonic())))
    raise TimeoutError('대시보드 HTTP 준비 시간이 초과되었습니다')


def main() -> int:
    api = os.getenv('API_URL', 'http://api-server:8000')
    print('[dashboard] 검색·추천 API 준비 완료를 기다립니다...', flush=True)
    wait_ready(api, float(os.getenv('READY_TIMEOUT_SECONDS', '21600')))
    print('[dashboard] 검색·추천 API 연결 완료', flush=True)
    process = subprocess.Popen([sys.executable, '-m', 'streamlit', 'run', 'dashboard/app.py',
                                '--server.port=8501', '--server.address=0.0.0.0'])
    previous = signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        wait_dashboard(process, 60)
        url = os.getenv('PUBLIC_DASHBOARD_URL', 'http://localhost:8501')
        print(f'[dashboard] {url} 에서 대시보드 시작', flush=True)
        return process.wait()
    finally:
        signal.signal(signal.SIGTERM, previous)
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == '__main__':
    raise SystemExit(main())
