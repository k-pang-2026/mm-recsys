"""Re-measure native dev HTTP after enabling the durable CT journal."""
from __future__ import annotations

from pathlib import Path

from src.common.artifacts import write_json
from src.common.config import load_config
from src.evaluation.api_benchmark import benchmark
from src.evaluation.reporting import environment


def main() -> int:
    cfg = load_config()
    report = benchmark(cfg)
    report.update(scale=cfg['scale'], acceptance='UNMEASURED', environment=environment(),
                  ct_scope='CT journal enabled; current registered dev v1.0; no production retraining',
                  nominal_targets=dict(search_p95_ms=cfg['targets']['search_p95_ms'],
                                       recommend_p95_ms=cfg['targets']['recommend_p95_ms']))
    report['checks'] = dict(search_http_p95=all(report['modes'][mode]['http']['p95_ms'] <= cfg['targets']['search_p95_ms']
                                                for mode in ('text', 'image', 'hybrid')),
                            recommend_http_p95=report['modes']['recommendation']['http']['p95_ms'] <= cfg['targets']['recommend_p95_ms'])
    write_json(Path(cfg['paths']['results_dir']) / f'ct_serving_{cfg["scale"]}.json', report)
    return 0 if all(report['checks'].values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
