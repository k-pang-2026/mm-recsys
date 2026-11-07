"""Korean diagnostics on stderr; machine-readable results stay on stdout."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import sys
from typing import Any, Callable


def configure_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='backslashreplace')
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    os.environ['PYTHONUTF8'] = '1'


def format_log(component: str, stage: str, message: str, *, status: str = '진행') -> str:
    at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    return f'[{at}] [{component} {stage}] [{status}] {message}'


def log(component: str, stage: str, message: str, *, status: str = '진행') -> None:
    print(format_log(component, stage, message, status=status), file=sys.stderr, flush=True)


def emit_json(value: Any, *, jsonl: bool = False) -> None:
    print(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=None if jsonl else 2), flush=True)


def status_ko(status: str) -> str:
    return {'PASS': '통과', 'FAIL': '실패', 'BLOCKED': '진행 불가',
            'UNMEASURED': '미측정', 'DEGENERATE': '통계 추론 불가',
            'MEASURED': '측정 완료', 'ALERT': '경고'}.get(status, status)


def report_metrics(rows: list[dict], component: str = '평가') -> None:
    for row in rows:
        status = row['status']
        action = '' if status == 'PASS' else ' / 다음 조치: 원본 결과의 평가 조건과 실패 항목을 확인하세요.'
        log(component, '검사', f"{row['name']}={row['value']} / 기준={row['target']}{action}",
            status=f'{status_ko(status)}({status})')


def run_cli(main: Callable[[], Any], component: str, action: str) -> Any:
    configure_utf8()
    try:
        return main()
    except SystemExit as error:
        if error.code:
            log(component, '종료', f'명령이 비정상 종료했습니다(code={error.code}). / 다음 조치: 위 검사 결과·원본 오류와 --help를 확인하세요.', status='실패')
        raise
    except Exception as error:
        log(component, '실행', f'원인: {type(error).__name__}: {error} / 다음 조치: {action}', status='실패')
        raise  # Keep the original exception chain and traceback for diagnosis.
