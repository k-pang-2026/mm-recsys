"""Losslessly archive a verified full A/B report below the repository file-size limit."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_submission_evidence import read_ab_evidence, read_json
from src.common.artifacts import file_hash, write_json


def archive(report_name: str, verification_name: str, output_name: str) -> dict:
    report = read_json(ROOT, report_name)
    verified = read_json(ROOT, verification_name)
    original_path = ROOT / report_name
    digest = file_hash(original_path)
    if (report['status'] != 'PASS' or report['scale'] != 'full' or verified['status'] != 'PASS'
            or verified['sha256'] != digest or verified['run_id'] != report['run_id']):
        raise ValueError('archive only the actual full report checked by the statistical verifier')
    output = ROOT / output_name
    if not output.resolve().is_relative_to(ROOT.resolve()) or output.exists():
        raise ValueError('choose a new repository-local archive path')
    retained = output.parent / 'raw' / original_path.name
    if retained.exists():
        raise ValueError('previous raw A/B evidence already exists; preserve it')
    compact = copy.deepcopy(report)
    shards: dict[str, list[dict]] = {}
    for arm in ('control', 'treatment'):
        entries = list(compact['arms'][arm]['arm_statistics'].items())
        compact['arms'][arm]['arm_statistics'] = {}
        shards[arm] = []
        for number, start in enumerate(range(0, len(entries), 15000)):
            path = output.parent / 'ab_statistics' / f'{arm}-{number:03d}.json'
            write_json(path, dict(entries[start:start + 15000]))
            if path.stat().st_size > 2_000_000:
                raise ValueError('A/B statistics shard exceeds repository limit')
            shards[arm].append(dict(source=str(path.relative_to(ROOT)), sha256=file_hash(path)))
    packed = dict(schema='ab-lossless-archive-v1', original_sha256=digest,
                  original_bytes=original_path.stat().st_size, original_local_source=str(retained.relative_to(ROOT)), report=compact,
                  arm_statistics_shards=shards,
                  verification=dict(source=verification_name, sha256=file_hash(ROOT / verification_name)),
                  scope='all original measured fields preserved; reconstruction must match original JSON bytes and verifier hash')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(packed, ensure_ascii=False, separators=(',', ':')) + '\n')
    if output.stat().st_size > 2_000_000 or read_ab_evidence(ROOT, output_name) != report:
        raise ValueError('lossless A/B archive verification failed')
    result = dict(verified, source=output_name, sha256=file_hash(output),
                  original_verification=packed['verification'], original_sha256=digest,
                  archive_schema=packed['schema'])
    write_json(output.parent / 'ab_acceptance_full.json', result)
    retained.parent.mkdir(parents=True, exist_ok=True)
    original_path.rename(retained)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', default='docs/results/integration/ab_full.json')
    parser.add_argument('--verification', default='docs/results/integration/ab_verification_full.json')
    parser.add_argument('--output', default='docs/results/integration/ab_full_archive.json')
    args = parser.parse_args()
    result = archive(args.report, args.verification, args.output)
    print(f"Full A/B lossless archive PASS: {result['source']}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
