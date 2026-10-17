"""Internal model reload with preloading off the request pointer and an atomic swap."""
from __future__ import annotations

import ipaddress
import logging
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from src.ct.storage import file_lock, append_log
from src.serving.model_loader import load_record

LOG = logging.getLogger(__name__)
router = APIRouter()


class ReloadRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: str | None = None


def require_internal(request: Request) -> None:
    try:
        allowed = request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        allowed = False
    # Do not trust Host / X-Forwarded-For. Container workers call the API over its
    # own loopback; exposing this route through a local reverse proxy is unsupported.
    if not allowed:
        raise HTTPException(403, 'local/internal operation; call API loopback directly')
    if request.app.state.ct is None:
        raise HTTPException(503, 'CT is disabled')


@router.post('/api/admin/reload')
def reload_model(payload: ReloadRequest, request: Request) -> dict:
    require_internal(request)
    _, _, registry = request.app.state.ct
    version = payload.version or registry.read()['active']
    if not version or version != registry.read()['active']:
        raise HTTPException(409, 'only the registry active version may be loaded; rollback the registry first')
    try:
        current = request.app.state.recommend
        replacement = load_record(registry, version, request.app.state.store,
                                  scoring=getattr(current, 'scoring', None))
        if current is not None and hasattr(current, 'data'):
            old_catalog = current.data['manifest']['file_hashes']['products.parquet']
            if replacement.data['manifest']['file_hashes']['products.parquet'] != old_catalog:
                raise ValueError('catalog migration requires coordinated search/model deployment')
        with file_lock(registry.lock):
            if registry.read()['active'] != version:
                raise HTTPException(409, 'active model changed during preload; retry')
            registry.verify(version)
            append_log(registry.log, dict(event='reloaded', version=version))
            request.app.state.recommend = replacement
            request.app.state.model_version = version
    except HTTPException:
        raise
    except Exception:
        LOG.exception('Model preload failed; current service retained')
        raise HTTPException(409, 'model preload/compatibility check failed; current service retained')
    return dict(status='reloaded', version=version)
