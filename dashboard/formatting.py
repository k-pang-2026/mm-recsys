"""Presentation only: keep stored timestamps and numeric precision unchanged."""
from __future__ import annotations

from datetime import datetime
import math
import re
from typing import Any

import numpy as np
import pandas as pd
from pandas.io.formats.style import Styler


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
    return frame.style.format(display_value, na_rep='—')
