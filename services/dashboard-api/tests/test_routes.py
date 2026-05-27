"""Route-shape tests using an in-memory store. No DB required."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from cascadia_dashboard.app import create_app
from cascadia_dashboard.store import InMemoryStore
from cascadia_dashboard.types import (
    ClusterRow,
    EventRow,
    Overview,
    ParetoPoint,
    RecentVerdict,
)


@pytest.fixture
def store() -> InMemoryStore:
    s = InMemoryStore()
    s.overview_data = Overview(
        window_seconds=3600,
        request_count=42,
        avg_latency_ms=1.8,
        escalation_rate=0.25,
        success_rate=1.0,
        mean_judge_score=0.78,
        judge_sample_size=18,
    )
    s.clusters_data = [
        ClusterRow(
            cluster_id="cluster-0",
            request_count=20,
            escalation_rate=0.1,
            mean_judge_score=0.85,
            judge_sample_size=10,
        ),
        ClusterRow(
            cluster_id="cluster-1",
            request_count=18,
            escalation_rate=0.4,
            mean_judge_score=0.6,
            judge_sample_size=8,
        ),
    ]
    s.events_data = [
        EventRow(
            request_id="req-1",
            occurred_at=datetime.now(timezone.utc),
            route="chat_completions",
            provider="openai",
            model="mock-cheap",
            upstream_status=200,
            elapsed_ms=12,
            cluster_id="cluster-0",
            escalated=False,
        ),
    ]
    s.verdicts_data = [
        RecentVerdict(
            score_id="score-1",
            pair_id="pair-1",
            judge_name="pairwise_preference_v1",
            prompt_variant="pairwise/v1",
            score=0.8,
            confidence=0.9,
            occurred_at=datetime.now(timezone.utc),
            cluster_id="cluster-0",
            cheap_model="mock-cheap",
            expensive_model="mock-expensive",
        ),
    ]
    s.pareto_data = [
        ParetoPoint(cluster_id="cluster-0", escalation_rate=0.1, mean_quality=0.85, sample_size=10),
        ParetoPoint(cluster_id="cluster-1", escalation_rate=0.4, mean_quality=0.6,  sample_size=8),
    ]
    return s


@pytest.fixture
def client(store: InMemoryStore) -> TestClient:
    app = create_app(store=store)
    with TestClient(app) as tc:
        yield tc


def test_health(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "cascadia-dashboard-api"


def test_overview(client: TestClient) -> None:
    r = client.get("/api/overview?window_minutes=60")
    assert r.status_code == 200
    body = r.json()
    assert body["request_count"] == 42
    assert body["mean_judge_score"] == 0.78


def test_clusters(client: TestClient) -> None:
    r = client.get("/api/clusters")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert body[0]["cluster_id"] == "cluster-0"


def test_recent_events_limit_validates(client: TestClient) -> None:
    r = client.get("/api/events/recent?limit=0")
    assert r.status_code == 422
    r = client.get("/api/events/recent?limit=10")
    assert r.status_code == 200


def test_recent_verdicts(client: TestClient) -> None:
    r = client.get("/api/verdicts/recent")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["score"] == 0.8


def test_pareto(client: TestClient) -> None:
    r = client.get("/api/pareto")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert body[0]["mean_quality"] > body[1]["mean_quality"]


def test_cors_default_closes(client: TestClient) -> None:
    # Default: no CORS origin set → no `Access-Control-Allow-Origin` header
    # in the response. Operators opt in via CASCADIA_DASHBOARD_CORS_ORIGINS.
    r = client.get("/api/health", headers={"Origin": "http://example.com"})
    # CORSMiddleware will omit the header entirely when the origin isn't allowed.
    assert r.headers.get("access-control-allow-origin") is None
