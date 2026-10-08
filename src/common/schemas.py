"""API models are frozen before search, recommendation and platform develop in parallel."""
from __future__ import annotations

from typing import Literal, Protocol
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query_text: str | None = None
    query_image: str | None = None
    top_k: int = Field(default=10, ge=1, le=100)

    @model_validator(mode='after')
    def require_input(self) -> 'SearchRequest':
        if not (self.query_text and self.query_text.strip()) and not self.query_image:
            raise ValueError('query_text or query_image is required')
        if self.query_image:
            import base64
            from io import BytesIO
            from PIL import Image
            try:
                raw = self.query_image.split(",",1)[1] if self.query_image.startswith("data:") else self.query_image
                decoded = base64.b64decode(raw,validate=True)
                with Image.open(BytesIO(decoded)) as image:
                    image.verify()
            except Exception as error:
                raise ValueError("query_image must be a valid base64-encoded image") from error
        return self


class SearchItem(BaseModel):
    product_id: str
    name: str
    score: float
    price: float


class SearchResponse(BaseModel):
    search_type: Literal['text', 'image', 'hybrid']
    results: list[SearchItem]
    latency_ms: float
    total_count: int


class RecommendationItem(BaseModel):
    product_id: str
    score: float
    reason: str
    is_exploration: bool = False


class PipelineLatency(BaseModel):
    candidate_ms: float = 0
    ranking_ms: float = 0
    reranking_ms: float = 0
    total_ms: float = 0


class SessionContext(BaseModel):
    recent_clicks: list[str] = Field(default_factory=list)
    session_interest: str | None = None


class RecommendResponse(BaseModel):
    user_id: str
    recommendations: list[RecommendationItem]
    pipeline_latency: PipelineLatency
    session_context: SessionContext


class EventRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    event_id: str
    user_id: str
    product_id: str
    event_type: Literal['view', 'cart', 'purchase']
    session_id: str = 'default'
    category: str | None = None


class FeedbackRequest(EventRequest):
    pass


class UserFeatures(BaseModel):
    recent_clicks: list[str] = Field(default_factory=list)
    session_clicks: int = 0
    session_interest: str | None = None
    profile: dict[str, str | float | int] = Field(default_factory=dict)


class FeatureStore(Protocol):
    def get_features(self, user_id: str) -> UserFeatures: ...
    def append_event(self, event: EventRequest) -> bool: ...
    def update_reward(self, feedback: FeedbackRequest) -> bool: ...
    def batch_load_profiles(self, profiles: dict[str, dict]) -> None: ...


class SearchService(Protocol):
    def search(self, request: SearchRequest) -> SearchResponse: ...


class RecommendationService(Protocol):
    def recommend(self, user_id: str, top_n: int) -> RecommendResponse: ...
