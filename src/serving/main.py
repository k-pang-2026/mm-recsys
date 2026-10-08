from __future__ import annotations

import importlib
import importlib.util
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Request

from src.common.config import load_config
from src.common.schemas import EventRequest, FeedbackRequest, RecommendResponse, SearchRequest, SearchResponse
from src.serving.memory_store import MemoryFeatureStore


def create_app(cfg: dict | None = None, search_service=None, recommend_service=None,
               feature_store=None) -> FastAPI:
    cfg = cfg or load_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        serving = cfg['serving']
        app.state.store = feature_store or MemoryFeatureStore(
            serving['history_limit'], serving['session_ttl_seconds'], serving['feedback_ttl_seconds'])
        for kind, supplied in [('search', search_service), ('recommend', recommend_service)]:
            backend = supplied
            module_name = serving['plugins'][kind]
            if backend is None and importlib.util.find_spec(module_name) is not None:
                backend = importlib.import_module(module_name).create_service(cfg, app.state.store)
            setattr(app.state, kind, backend)
        yield

    app = FastAPI(title='MM Search & Recommend', lifespan=lifespan)

    @app.get('/health')
    def health(request: Request) -> dict:
        return {'status': 'ok', 'search_ready': request.app.state.search is not None,
                'recommend_ready': request.app.state.recommend is not None, 'scale': cfg['scale']}

    @app.get('/ready')
    def ready(request: Request) -> dict:
        if request.app.state.search is None or request.app.state.recommend is None:
            raise HTTPException(503, 'search/recommend model implementations are not ready')
        return {'status': 'ready'}

    @app.post('/api/search', response_model=SearchResponse)
    def search(payload: SearchRequest, request: Request):
        if request.app.state.search is None:
            raise HTTPException(503, 'SearchService unavailable; A implements B2a/B2b')
        return request.app.state.search.search(payload)

    @app.get('/api/recommend', response_model=RecommendResponse)
    def recommend(request: Request, user_id: str, top_n: int = Query(10, ge=1, le=100)):
        if request.app.state.recommend is None:
            raise HTTPException(503, 'RecommendationService unavailable; B implements B3-B5')
        return request.app.state.recommend.recommend(user_id, top_n)

    @app.post('/api/event')
    def event(payload: EventRequest, request: Request) -> dict:
        applied = request.app.state.store.append_event(payload)
        return {'applied': applied, 'features': request.app.state.store.get_features(payload.user_id)}

    @app.post('/api/feedback')
    def feedback(payload: FeedbackRequest, request: Request) -> dict:
        return {'applied': request.app.state.store.update_reward(payload)}

    return app


app = create_app()
