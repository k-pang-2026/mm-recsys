"""Small durable CT journal and cross-process locks (local filesystem only)."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def file_lock(path: Path, *, blocking: bool = True):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if os.name == 'nt':
            import importlib
            msvcrt = importlib.import_module('msvcrt')
            if path.stat().st_size == 0:
                stream.write(b'0'); stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def append_log(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(path.parent / '.cache' / 'ct-locks' / f'{path.name}.lock'):
        with path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(at=utc_now(), **value), ensure_ascii=False, allow_nan=False) + '\n')
            stream.flush(); os.fsync(stream.fileno())


class Journal:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY, user_id TEXT NOT NULL, at REAL NOT NULL,
                    items TEXT NOT NULL, top_n INTEGER NOT NULL, version TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                    user_id TEXT NOT NULL, product_id TEXT NOT NULL, kind TEXT NOT NULL,
                    at REAL NOT NULL, request_id TEXT, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS event_request ON events(request_id);
            ''')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    def exposure(self, request_id: str, user_id: str, products: list[str], top_n: int,
                 version: str, at: float) -> None:
        if len(set(products)) != len(products) or len(products) > top_n or top_n < 1:
            raise ValueError('invalid exposure list')
        with self.connect() as db:
            db.execute('INSERT INTO requests VALUES (?,?,?,?,?,?)',
                       (request_id, user_id, at, json.dumps(products), top_n, version))

    def event(self, payload: dict, at: float, request_id: str | None = None,
              window_seconds: int = 3600) -> bool:
        if payload['event_type'] not in ('view', 'cart', 'purchase'):
            raise ValueError('unsupported CT event')
        with self.connect() as db:
            if request_id:
                row = db.execute('SELECT * FROM requests WHERE id=?', (request_id,)).fetchone()
                if (row is None or row['user_id'] != payload['user_id']
                        or payload['product_id'] not in json.loads(row['items'])
                        or not row['at'] <= at <= row['at'] + window_seconds):
                    raise ValueError('unattributable recommendation outcome')
            return db.execute('INSERT OR IGNORE INTO events(id,user_id,product_id,kind,at,request_id,payload) '
                              'VALUES (?,?,?,?,?,?,?)', (payload['event_id'], payload['user_id'],
                              payload['product_id'], payload['event_type'], at, request_id,
                              json.dumps(payload))).rowcount == 1

    def high_watermark(self) -> int:
        with self.connect() as db:
            return int(db.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0])

    def count_since(self, seq: int, through: int | None = None) -> int:
        with self.connect() as db:
            return int(db.execute('SELECT COUNT(*) FROM events WHERE seq>? AND seq<=?',
                                  (seq, through if through is not None else self.high_watermark())).fetchone()[0])
