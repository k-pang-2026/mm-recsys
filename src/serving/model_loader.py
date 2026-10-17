"""C adapter for B's immutable v1.0 loaders; releases retain models/v{major}.{minor}."""
from __future__ import annotations

from typing import Any

import copy
import tempfile
from pathlib import Path

from src.ct.model_registry import ModelRegistry


def load_record(registry: ModelRegistry, version: str, store: Any, *, scoring: dict | None = None) -> Any:
    from src.recommendation.service import create_service
    record = registry.verify(version)
    cfg = copy.deepcopy(record['config'])
    if scoring is not None:
        cfg['recommend']['scoring'] = copy.deepcopy(scoring)
    cfg['paths']['data_dir'] = record['data_path']
    cfg['recommend'].pop('candidate_bundle', None)
    # B loaders intentionally share the fixed v1.0 format. A transient directory
    # view exposes one complete immutable release to all three loaders together.
    # No model is copied or modified; all inference objects are resident on return.
    with tempfile.TemporaryDirectory(prefix='mm-ct-load-') as temporary:
        Path(temporary, 'v1.0').symlink_to(record['bundle_path'], target_is_directory=True)
        cfg['paths']['model_dir'] = temporary
        # Avoid B's optional RECOMMEND_MODEL_DIR override bypassing this release.
        import os
        if os.getenv('RECOMMEND_MODEL_DIR'):
            raise ValueError('unset RECOMMEND_MODEL_DIR when loading a registered release')
        service = create_service(cfg, store)
    if service is None:
        raise ValueError('release is incomplete')
    # Serving does not access model files after loading. Preserve meaningful metadata.
    service.cfg['paths']['model_dir'] = str(registry.root)
    service.cfg['recommend']['candidate_bundle'] = record['bundle_path']
    service.ct_version = version
    service.recommend('__ct_warmup__', 1)
    return service
