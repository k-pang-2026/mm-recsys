"""Small durable CT journal and cross-process locks (local filesystem only)."""
from __future__ import annotations

from typing import Iterator, Iterable

from contextlib import contextmanager, closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3

from src.common.console import log, status_ko


def describe_event(value: dict) -> None:
    event = value.get('event')
    if event == 'training_deferred':
        log('CT', '학습 대기', '신규 로그 수는 충분하지만 train/valid의 실제 노출·클릭·구매 라벨이 부족합니다. '
            '추천 request_id에 연결된 후속 행동을 수집하세요. 기존 모델과 미처리 로그는 유지합니다. '
            f"/ 상세={value['data_path']}", status='경고')
        return
    if os.getenv('CT_OUTPUT') == 'human':
        if event == 'monitor':
            thresholds = value['thresholds']
            measured = lambda v: '미측정 (성숙한 관측 표본 부족)' if v is None else f'{v:.4f}'
            log('CT Monitor', '', f"현재 HitRate@50: {measured(value['hit_rate_at_50'])} "
                f"(임계값: {thresholds['hitrate_threshold']}) / CTR: {measured(value['ctr'])}")
            if value['alerts']:
                log('CT Monitor', '알림', '성능 저하 감지! 재학습을 권장합니다.', status='경고')
            return
        if event == 'training_started':
            log('CT Trigger', '', f"신규 로그 {value['new_events']:,}건 축적 / "
                f"모델 {value['parent']} → {value['version']} / 모델 재학습 트리거됨...")
            return
        if event in ('promoted', 'retained'):
            decision = '승격' if event == 'promoted' else '기존 모델 유지'
            log('CT Trigger', '', f"재학습 완료. 후보 모델: {value['version']} / 활성 모델: {value['active']} / {decision}")
            return
    if event == 'monitor':
        thresholds = value['thresholds']
        log('CT', '알림' if value['alerts'] else '모니터링',
            f"CTR={value['ctr']} / 기준={thresholds['ctr_threshold']} / "
            f"HitRate@50={value['hit_rate_at_50']} / 기준={thresholds['hitrate_threshold']} / "
            f"성숙 요청={value['mature_requests']} / 노출={value['exposures']} / "
            + ('성능 저하 감지. 다음 조치: 표본과 재학습 누적 로그를 확인하세요.' if value['alerts']
               else '관측 완료. null은 관측 표본 부족으로 미측정입니다.'),
            status='경고' if value['alerts'] else status_ko(value['status']))
    elif event == 'training_started':
        log('CT', '재학습', f"신규 로그 {value['new_events']:,}건 누적 / {value['parent']} → {value['version']} / 재학습 시작")
    elif event in ('promoted', 'retained'):
        message = '검증 조건을 충족하여 새 모델을 승격합니다.' if event == 'promoted' else '검증 개선 조건을 충족하지 못해 기존 모델을 유지합니다.'
        log('CT', '판정', f"{message} / 후보={value['version']} / 활성={value['active']} / 검증={value['comparison']}", status='승격' if event == 'promoted' else '유지')
    elif event in ('training_failed', 'reload_retry'):
        log('CT', '재학습' if event == 'training_failed' else '모델 재로딩',
            f"원인: {value['error']} / 다음 조치: 원본 오류와 모델·API 상태를 확인한 뒤 재시도하세요.", status='실패')
    elif event == 'rollback':
        log('CT', '롤백', f"{value['version']} → {value['active']} / 사유={value['reason']}", status='성공')
    elif event in ('registered', 'initialized', 'reloaded'):
        stage = {'registered': '버전 등록', 'initialized': '초기화', 'reloaded': '서비스 모델 교체'}[event]
        log('CT', stage, f"모델={value['version']}", status='성공')

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def file_lock(path: Path, *, blocking: bool = True) -> Iterator[None]:
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
    describe_event(value)


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

    def connect(self) -> sqlite3.Connection:
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
        return self.events([(payload, at)], request_id, window_seconds) == 1

    def events(self, entries: Iterable[tuple[dict, float]], request_id: str | None = None,
               window_seconds: int = 3600) -> int:
        """One durable transaction per batch; any invalid entry rolls back the batch."""
        with closing(self.connect()) as db, db:
            before = db.total_changes
            for payload, at in entries:
                if payload['event_type'] not in ('view', 'cart', 'purchase'):
                    raise ValueError('unsupported CT event')
                if request_id:
                    row = db.execute('SELECT * FROM requests WHERE id=?', (request_id,)).fetchone()
                    if (row is None or row['user_id'] != payload['user_id']
                            or payload['product_id'] not in json.loads(row['items'])
                            or not row['at'] <= at <= row['at'] + window_seconds):
                        raise ValueError('unattributable recommendation outcome')
                db.execute('INSERT OR IGNORE INTO events(id,user_id,product_id,kind,at,request_id,payload) '
                           'VALUES (?,?,?,?,?,?,?)', (payload['event_id'], payload['user_id'],
                           payload['product_id'], payload['event_type'], at, request_id, json.dumps(payload)))
            return db.total_changes - before

    def high_watermark(self) -> int:
        with self.connect() as db:
            return int(db.execute('SELECT COALESCE(MAX(seq),0) FROM events').fetchone()[0])

    def count_since(self, seq: int, through: int | None = None) -> int:
        with self.connect() as db:
            return int(db.execute('SELECT COUNT(*) FROM events WHERE seq>? AND seq<=?',
                                  (seq, through if through is not None else self.high_watermark())).fetchone()[0])
