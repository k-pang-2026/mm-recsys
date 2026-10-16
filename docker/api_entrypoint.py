"""Liveness during single-owner preparation, then the shared JSON/multipart API."""
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import subprocess
import sys
import threading


class PreparingHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        healthy = self.path == '/health'
        payload = json.dumps(dict(status='preparing', search_ready=False, recommend_ready=False)).encode()
        self.send_response(200 if healthy else 503)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            # Bounded readiness clients may disconnect before a busy host replies.
            pass

    do_POST = do_GET

    def log_message(self, *args) -> None:
        pass


class PreparationServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    server = PreparationServer(('0.0.0.0', 8000), PreparingHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        subprocess.run([sys.executable, 'scripts/prepare_all.py'], check=True,
                       timeout=float(os.getenv('PREPARE_TIMEOUT_SECONDS', '21600')))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    from docker.runtime import runtime_config, config_path
    cfg = runtime_config()
    os.environ['CONFIG_PATH'] = str(config_path(cfg))
    from pathlib import Path
    manifest = json.loads((Path(cfg['paths']['data_dir']) / 'split_manifest.json').read_text())
    print(f"PREPARATION COMPLETE; catalog={manifest['counts']['products']}; "
          f"CLIP={cfg['search']['clip_model']}@{cfg['search']['clip_revision']}; "
          'FAISS + Two Tower/DeepFM/session', flush=True)
    os.execvp('uvicorn', ['uvicorn', 'docker.serve:app', '--host', '0.0.0.0', '--port', '8000',
                          '--workers', '1', '--no-access-log'])


if __name__ == '__main__':
    main()
