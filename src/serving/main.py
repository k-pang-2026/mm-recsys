from __future__ import annotations

from typing import Any, AsyncIterator

import importlib
import importlib.util
import time
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Request, Response

from src.common.config import load_config
from src.common.schemas import EventRequest, FeedbackRequest, RecommendResponse, SearchRequest, SearchResponse
from src.serving.feature_store import create_feature_store
from src.serving.ct_admin import router as ct_router
from src.ct.retrain_trigger import components
from src.serving.model_loader import load_record


def create_app(cfg: dict | None = None, search_service: Any=None, recommend_service: Any=None,
               feature_store: Any=None) -> FastAPI:
    cfg = cfg or load_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        serving = cfg['serving']
        app.state.store = feature_store if feature_store is not None else create_feature_store(cfg)
        app.state.ct = components(cfg) if serving.get('ct', {}).get('enabled', False) else None
        active = app.state.ct[2].read()['active'] if app.state.ct else None
        app.state.model_version = active or 'v1.0'
        for kind, supplied in [('search', search_service), ('recommend', recommend_service)]:
            backend = supplied
            module_name = serving['plugins'][kind]
            if backend is None and kind == 'recommend' and active:
                assert app.state.ct is not None
                backend = load_record(app.state.ct[2], active, app.state.store,
                                      scoring=cfg['recommend'].get('scoring'))
            if backend is None and importlib.util.find_spec(module_name) is not None:
                backend = importlib.import_module(module_name).create_service(cfg, app.state.store)
            setattr(app.state, kind, backend)
        try:
            yield
        finally:
            if feature_store is None and hasattr(app.state.store, 'close'):
                app.state.store.close()

    app = FastAPI(title='MM Search & Recommend', lifespan=lifespan)

    app.include_router(ct_router)

    @app.get('/health')
    def health(request: Request) -> dict:
        return {'status': 'ok', 'search_ready': request.app.state.search is not None,
                'recommend_ready': request.app.state.recommend is not None, 'scale': cfg['scale'],
                'model_version': request.app.state.model_version}

    @app.get('/ready')
    def ready(request: Request) -> dict:
        if request.app.state.search is None or request.app.state.recommend is None:
            raise HTTPException(503, 'search/recommend model implementations are not ready')
        return {'status': 'ready'}

    @app.post('/api/search', response_model=SearchResponse)
    def search(payload: SearchRequest, request: Request) -> Any:
        if request.app.state.search is None:
            raise HTTPException(503, 'SearchService unavailable; A implements B2a/B2b')
        return request.app.state.search.search(payload)

    @app.get('/api/recommend', response_model=RecommendResponse)
    def recommend(request: Request, response: Response, user_id: str, top_n: int = Query(10, ge=1, le=100)) -> Any:
        # Capture one resident pointer; an in-flight request completes on its old bundle.
        service = request.app.state.recommend
        if service is None:
            raise HTTPException(503, 'RecommendationService unavailable; B implements B3-B5')
        result = service.recommend(user_id, top_n)
        if request.app.state.ct is not None:
            request_id = uuid.uuid4().hex
            request.app.state.ct[1].exposure(request_id, user_id,
                [item.product_id for item in result.recommendations], top_n,
                getattr(service, 'ct_version', 'v1.0'), time.time())
            response.headers['X-Recommendation-Request-ID'] = request_id
        return result

    def record_outcome(payload: Any, request: Request) -> None:
        if request.app.state.ct is not None:
            spec, journal, _ = request.app.state.ct
            try:
                journal.event(payload.model_dump(), time.time(),
                              request.headers.get('X-Recommendation-Request-ID'), spec['attribution_seconds'])
            except ValueError as error:
                raise HTTPException(422, str(error))

    @app.post('/api/event')
    def event(payload: EventRequest, request: Request) -> dict:
        record_outcome(payload, request)
        try:
            applied = request.app.state.store.append_event(payload)
        except ConnectionError as error:
            raise HTTPException(503, 'event storage unavailable; retry the same event ID') from error
        return {'applied': applied, 'features': request.app.state.store.get_features(payload.user_id)}

    @app.post('/api/feedback')
    def feedback(payload: FeedbackRequest, request: Request) -> dict:
        record_outcome(payload, request)
        try:
            return {'applied': request.app.state.store.update_reward(payload)}
        except ConnectionError as error:
            raise HTTPException(503, 'feedback storage unavailable; retry the same event ID') from error

    return app


app = create_app()
