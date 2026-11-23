"""Presentation only: keep stored timestamps and numeric precision unchanged."""
from __future__ import annotations

from datetime import datetime
import math
import re
from typing import Any

import numpy as np
import pandas as pd
from pandas.io.formats.style import Styler


# English sentences that result files carry into visible text, in Korean. The files and 근거 views keep the original.
KOREAN = {
    'not the B11 final acceptance bundle': 'B11(최종 제출 검사) 단계의 최종 판정 묶음은 아닙니다.',
    'A/B and CT production improvement are separate': 'A/B 실험과 CT의 운영 개선 효과는 이 결과에 포함되지 않고 따로 확인합니다.',
    'fixed-origin recommendation quality uses B5 memory adapter; live Redis state and attributed rewards are measured separately':
        '추천 품질은 고정 시점 데이터를 메모리 저장소(B5 단계 구현)에 넣어 쟀고, 실제 Redis 상태와 클릭·구매 보상은 따로 측정했습니다.',
    'independent-user cluster delta variance; descriptive simulated effect': '사용자 단위로 묶어 계산한 분산 · 합성 실험의 설명용 효과',
    'no result or user-vector cache': '캐시 없음 (결과와 사용자 벡터를 매번 새로 계산)',
    'controlled rollback drill after measured promotion': '승격을 측정한 뒤 진행한 통제 롤백 연습',
    'isolated full functional rollback after measured controlled initial promotion': '통제된 첫 승격을 측정한 뒤 격리 환경에서 진행한 전체 기능 롤백',
    'Frozen calibration applied at full scale; descriptive external-reference distances only, no selection based on these results':
        '고정한 교정 설정을 full 규모에 적용한 결과이며, 실제 데이터와의 거리를 보여 주기만 하고 이 값으로 설정을 고르지 않았습니다.',
}
CT_EVENTS = dict(initialized='초기 등록', registered='후보 등록', promoted='승격', rollback='롤백')


def korean(text: Any) -> Any:
    """Known English result-file sentences in Korean; anything else unchanged."""
    return KOREAN.get(text, text) if isinstance(text, str) else text


def display_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: display_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [display_value(item) for item in value]
    if value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, (datetime, pd.Timestamp)) or (
        isinstance(value, str) and re.match(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}', value)
    ):
        try:
            timestamp = pd.Timestamp(value)
            if timestamp.tzinfo is None:
                timestamp = timestamp.tz_localize('UTC')
            return timestamp.tz_convert('Asia/Seoul').strftime('%Y-%m-%d %H:%M:%S KST')
        except ValueError:
            return value
    if isinstance(value, (float, np.floating)):
        if not math.isfinite(value):
            return None
        # Keep tiny nonzero probabilities and thresholds distinguishable from zero.
        return f'{value:.1e}' if 0 < abs(value) < .05 else f'{value:.1f}'
    return value


def display_frame(frame: pd.DataFrame) -> Styler:
    styled = frame.style.format(display_value, na_rep='—')
    if '기준' in frame:
        styled.format('{:g}', subset=['기준'], na_rep='—')
    return styled
