"""Wire types for the read API. Pydantic v2 so FastAPI emits a clean
OpenAPI schema the Next.js client can consume."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class Overview(BaseModel):
    window_seconds: int
    request_count: int
    avg_latency_ms: float | None
    escalation_rate: float | None = Field(ge=0.0, le=1.0, default=None)
    # Phase 7.1 surface: fraction of requests that carried `tools=[...]`.
    # Cascade bypasses escalation on those requests, so a non-trivial
    # tools_use_rate explains a low escalation_rate without it being a bug.
    tools_use_rate: float | None = Field(ge=0.0, le=1.0, default=None)
    success_rate: float | None = Field(ge=0.0, le=1.0, default=None)
    mean_judge_score: float | None = Field(ge=0.0, le=1.0, default=None)
    judge_sample_size: int


class ClusterRow(BaseModel):
    cluster_id: str
    request_count: int
    escalation_rate: float | None
    mean_judge_score: float | None
    judge_sample_size: int
    cheap_provider: str | None = None
    expensive_provider: str | None = None
    # Phase 7.1 surface: fraction of requests on this cluster that carried
    # `tools=[...]`. Cascade bypasses escalation on tool-use traffic
    # (escalation rate is artificially 0% on those requests), so the
    # dashboard can use this to caveat the headline escalation number.
    tools_use_rate: float | None = None


class EventRow(BaseModel):
    request_id: str
    occurred_at: datetime
    route: str | None
    provider: str | None
    model: str | None
    upstream_status: int | None
    elapsed_ms: int
    cluster_id: str | None
    escalated: bool
    # True iff the inbound request carried non-empty `tools=[...]`. Used by
    # the activity page to badge tool-use rows so an operator can see why
    # `escalated: false` was the correct decision.
    tools_present: bool = False


class RecentVerdict(BaseModel):
    score_id: str
    pair_id: str
    judge_name: str
    prompt_variant: str
    # Nullable: a non-finite stored score (NaN/Inf) is coerced to null rather
    # than emitted as invalid JSON. See store._as_float.
    score: float | None
    confidence: float | None
    occurred_at: datetime
    cluster_id: str | None
    cheap_model: str | None
    expensive_model: str | None


class ParetoPoint(BaseModel):
    cluster_id: str
    escalation_rate: float = Field(ge=0.0, le=1.0)
    mean_quality: float = Field(ge=0.0, le=1.0)
    sample_size: int


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
