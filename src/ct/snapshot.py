"""Compact observed-data snapshots; journal rows are decoded in bounded batches."""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import shutil
import tempfile

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from src.common.artifacts import file_hash, fingerprint, write_json
from src.ct.storage import Journal


def first_by_id(table: pa.Table, field: str) -> pa.Table:
    first = pc.index_in(table[field], value_set=table[field])
    return table.filter(pc.equal(first, pa.array(np.arange(len(table), dtype=np.int32))))


def journal_tables(source: Path, journal: Journal, after: int, through: int) -> tuple[pa.Table, pa.Table]:
    events = pq.read_table(source / 'events.parquet')
    impressions = pq.read_table(source / 'impressions.parquet')
    event_parts, exposure_parts = [events], [impressions]
    with closing(journal.connect()) as db:
        cursor = db.execute('SELECT * FROM events WHERE seq>? AND seq<=? ORDER BY seq', (after, through))
        while rows := cursor.fetchmany(10000):
            incoming = []
            for row in rows:
                payload = json.loads(row['payload'])
                incoming.append(dict(event_id=row['id'], user_id=row['user_id'], product_id=row['product_id'],
                    event_type=row['kind'], timestamp=pd.Timestamp(row['at'], unit='s', tz='UTC'),
                    session_id=payload.get('session_id', 'default'), query=None,
                    impression_id=f"{row['request_id']}:{row['product_id']}" if row['request_id'] else None,
                    position=None))
            event_parts.append(pa.Table.from_pylist(incoming, schema=events.schema))
        cursor = db.execute('SELECT * FROM requests ORDER BY rowid')
        while requests := cursor.fetchmany(1000):
            exposures = [dict(impression_id=f"{r['id']}:{pid}", request_id=r['id'], user_id=r['user_id'],
                product_id=pid, exposed_at=pd.Timestamp(r['at'], unit='s', tz='UTC'), position=i + 1)
                for r in requests for i, pid in enumerate(json.loads(r['items']))]
            exposure_parts.append(pa.Table.from_pylist(exposures, schema=impressions.schema))
    return (first_by_id(pa.concat_tables(event_parts), 'event_id'),
            first_by_id(pa.concat_tables(exposure_parts), 'impression_id'))


def snapshot(source: Path, target: Path, events: pd.DataFrame | pa.Table,
             impressions: pd.DataFrame | pa.Table, cfg: dict) -> dict:
    original = json.loads((source / 'split_manifest.json').read_text())
    for name in ('products.parquet', 'users.parquet'):
        if file_hash(source / name) != original['file_hashes'][name]:
            raise ValueError(f'source checksum mismatch: {name}')
    if target.exists():
        raise ValueError('snapshot destination already exists')
    if isinstance(events, pd.DataFrame):
        events = pa.Table.from_pandas(events, preserve_index=False)
    if isinstance(impressions, pd.DataFrame):
        impressions = pa.Table.from_pandas(impressions, preserve_index=False)
    for table, field in ((events, 'event_id'), (impressions, 'impression_id')):
        if pc.count_distinct(table[field], mode='all').as_py() != len(table):
            raise ValueError(f'duplicate {field}')
    if not len(events) or events['timestamp'].null_count or impressions['exposed_at'].null_count:
        raise ValueError('missing observation time')
    ordered = events.sort_by([('timestamp', 'ascending'), ('event_id', 'ascending')])
    times = ordered['timestamp'].cast(pa.int64()).to_numpy()
    through = ordered['timestamp'][-1].as_py()
    impressions = impressions.filter(pc.less_equal(impressions['exposed_at'], pa.scalar(through)))
    n = len(ordered)
    boundaries = [int(n * cfg['split']['train']), int(n * (cfg['split']['train'] + cfg['split']['valid']))]
    # Exactly the existing 8/1/1 contract: equal timestamps stay in the earlier split.
    boundaries = [int(np.searchsorted(times, times[i - 1], side='right')) if 0 < i < n else i
                  for i in boundaries]
    a, b = boundaries; b = max(a, b)
    splits = {'train': ordered.slice(0, a), 'valid': ordered.slice(a, b-a), 'test': ordered.slice(b)}
    if any(not len(part) for part in splits.values()):
        raise ValueError('not enough distinct times for fresh train/valid/test splits')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent, prefix='.ct-snapshot-') as temporary:
        root = Path(temporary) / 'snapshot'; (root / 'split').mkdir(parents=True)
        for name in ('products.parquet', 'users.parquet'):
            shutil.copy2(source / name, root / name)
        pq.write_table(ordered, root / 'events.parquet')
        pq.write_table(impressions, root / 'impressions.parquet')
        for name, part in splits.items():
            pq.write_table(part, root / 'split' / f'{name}.parquet')
        files = ['products.parquet', 'users.parquet', 'events.parquet', 'impressions.parquet',
                 'split/train.parquet', 'split/valid.parquet', 'split/test.parquet']
        hashes = {name: file_hash(root / name) for name in files}
        manifest = dict(generator_version='ct-observed-snapshot-v2', scale=cfg['scale'], seed=cfg['seed'],
            generation_fingerprint=fingerprint(dict(files=hashes, seed=cfg['seed'], split=cfg['split'])),
            parent_fingerprint=original['generation_fingerprint'], file_hashes=hashes,
            counts=dict(products=pq.ParquetFile(root / 'products.parquet').metadata.num_rows,
                        users=pq.ParquetFile(root / 'users.parquet').metadata.num_rows,
                        events=len(ordered), impressions=len(impressions)),
            split_counts={name: len(part) for name, part in splits.items()},
            boundaries={name: dict(start=part['timestamp'][0].as_py().isoformat(),
                                  end=part['timestamp'][-1].as_py().isoformat()) for name, part in splits.items()},
            observed_through=through.isoformat(),
            scope='new chronological snapshot; train/valid only for fitting/selection; test unopened')
        write_json(root / 'split_manifest.json', manifest)
        root.rename(target)
    return manifest


def training_eligibility(root: Path, cfg: dict) -> dict:
    """Check real ranking labels before expensive model fitting; never invent exposures."""
    from src.recommendation.ranking_labels import build_labels
    manifest = json.loads((root / 'split_manifest.json').read_text())
    parts = [pq.read_table(root / 'split' / f'{name}.parquet') for name in ('train', 'valid')]
    events = pa.concat_tables(parts)
    linked_views = pc.and_(pc.equal(events['event_type'], 'view'), pc.is_valid(events['impression_id']))
    events = events.filter(pc.or_(linked_views, pc.equal(events['event_type'], 'purchase')))
    observed = events.to_pandas()
    impressions = pd.read_parquet(root / 'impressions.parquet')
    diagnostics = {}
    for name in ('train', 'valid'):
        start, end = (pd.Timestamp(manifest['boundaries'][name][key]) for key in ('start', 'end'))
        if not ((impressions.exposed_at >= start) & (impressions.exposed_at <= end)).any():
            diagnostics[name] = dict(rows=0, ctr_observed=0, cvr_observed=0, ctr_classes=0, cvr_classes=0)
            continue
        labels, counts = build_labels(impressions, observed[observed.timestamp <= end], start, end,
                                     cfg['recommend']['ranking']['attribution_seconds'])
        counts['ctr_classes'] = int(labels.loc[labels.ctr_mask, 'ctr'].nunique())
        counts['cvr_classes'] = int(labels.loc[labels.cvr_mask, 'cvr'].nunique())
        diagnostics[name] = counts
    return dict(ready=all(v['ctr_classes'] == v['cvr_classes'] == 2 for v in diagnostics.values()),
                splits=diagnostics, reason='train/valid require observed positive and negative CTR/CVR labels')
