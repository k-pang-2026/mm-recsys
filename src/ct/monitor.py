"""Recent, mature attributable CTR and request HitRate@50; missing evidence stays null."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from src.ct.storage import Journal, append_log

LOG = logging.getLogger(__name__)


def measure(journal: Journal, spec: dict, now: float) -> dict:
    window = int(spec['attribution_seconds'])
    start = now - int(spec['recent_seconds'])
    with journal.connect() as db:
        requests = db.execute('SELECT * FROM requests WHERE at>=? AND at+?<=?',
                              (start, window, now)).fetchall()
        outcomes = db.execute('SELECT request_id,product_id,kind,at FROM events '
                              'WHERE request_id IS NOT NULL AND at>=? AND at<=?', (start, now)).fetchall()
    linked: dict[str, list] = {}
    for event in outcomes:
        linked.setdefault(event['request_id'], []).append(event)
    exposures = clicks = hit_requests = top50_requests = 0
    for row in requests:
        ids = set(json.loads(row['items']))
        eligible = [e for e in linked.get(row['id'], [])
                    if row['at'] <= e['at'] <= row['at'] + window and e['product_id'] in ids]
        exposures += len(ids)
        clicks += len({e['product_id'] for e in eligible if e['kind'] == 'view'})
        if row['top_n'] == 50:
            top50_requests += 1
            hit_requests += int(any(e['kind'] in ('cart', 'purchase') for e in eligible))
    ctr = clicks / exposures if exposures else None
    hitrate = hit_requests / top50_requests if top50_requests else None
    minimum = int(spec['min_mature_requests'])
    alerts = []
    if len(requests) >= minimum and ctr is not None and ctr < float(spec['ctr_threshold']):
        alerts.append('ctr_below_threshold')
    if top50_requests >= minimum and hitrate is not None and hitrate < float(spec['hitrate_threshold']):
        alerts.append('hitrate_below_threshold')
    return dict(event='monitor', status='ALERT' if alerts else ('MEASURED' if requests else 'UNMEASURED'),
                ctr=ctr, hit_rate_at_50=hitrate, clicks=clicks, exposures=exposures,
                mature_requests=len(requests), top50_requests=top50_requests, hit_requests=hit_requests,
                alerts=alerts, window_start=start, observed_through=now, attribution_seconds=window,
                semantics='CTR: unique linked viewed items / mature exposed items; HitRate@50: '
                          'mature top50 requests with attributed cart/purchase / mature top50 requests; '
                          'online monitoring, distinct from fixed-origin offline quality',
                thresholds={k: spec[k] for k in ('ctr_threshold', 'hitrate_threshold', 'min_mature_requests')})


def monitor(journal: Journal, spec: dict, now: float, log: Path) -> dict:
    result = measure(journal, spec, now)
    append_log(log, result)
    if result['alerts']:
        LOG.warning('CT quality alert: %s', ', '.join(result['alerts']))
    return result
