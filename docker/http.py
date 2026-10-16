"""Bounded readiness wait and HTTP requests without adding runtime dependencies."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request


def request(url: str, payload: dict | None = None, *, timeout: float = 30) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as response:
        return json.load(response)


def wait_ready(url: str, timeout: float, interval: float = 2) -> None:
    deadline = time.monotonic() + timeout
    error = 'not attempted'
    while time.monotonic() < deadline:
        try:
            if request(url.rstrip('/') + '/ready', timeout=min(5, max(.01, deadline-time.monotonic()))).get('status') == 'ready':
                return
        except (OSError, ValueError) as exc:
            error = str(exc)
        time.sleep(min(interval, max(0, deadline-time.monotonic())))
    raise TimeoutError(f'API readiness timed out after {timeout}s: {error}')
