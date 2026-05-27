"""Tests for the labeling write surface (onboard, next, submit, progress).

Uses `InMemoryCalibrationStore` so no DB is needed. Verifies:
  - Onboarding is idempotent and returns `already_existed=False` the first time.
  - The same pair stays at the same swap direction across requests (deterministic).
  - Submitting a label removes the pair from the queue.
  - Progress correctly counts attention-check pass/fail with un-swap applied.
"""

from __future__ import annotations

import asyncpg
import pytest
from fastapi.testclient import TestClient

from cascadia_dashboard.app import create_app
from cascadia_dashboard.calibrate import InMemoryCalibrationStore
from cascadia_dashboard.calibrate.store import decide_swap
from cascadia_dashboard.store import InMemoryStore


@pytest.fixture
def calibration_store() -> InMemoryCalibrationStore:
    store = InMemoryCalibrationStore()
    store.seed_pair(
        pair_id="p1",
        prompt="What is 2+2?",
        response_a="4",
        response_b="14",
        cluster_id="math",
    )
    store.seed_pair(
        pair_id="p2",
        prompt="Capital of France?",
        response_a="Paris",
        response_b="Berlin",
        cluster_id="factual",
    )
    store.seed_pair(
        pair_id="attn-1",
        prompt="2+2?",
        response_a="4",
        response_b="14",
        cluster_id="attention",
        attention_check_answer="a",
    )
    return store


@pytest.fixture
def client(calibration_store: InMemoryCalibrationStore) -> TestClient:
    app = create_app(store=InMemoryStore(), calibration_store=calibration_store)
    with TestClient(app) as tc:
        yield tc


def test_decide_swap_is_deterministic() -> None:
    assert decide_swap(pair_id="p1", reviewer_id="chris") == decide_swap(
        pair_id="p1", reviewer_id="chris"
    )


def test_decide_swap_differs_across_reviewers() -> None:
    # With pair fixed, sweep many reviewers — should not all collapse to one direction.
    flips = {decide_swap(pair_id="p1", reviewer_id=f"r{i}") for i in range(50)}
    assert flips == {True, False}, "swap decision should produce both directions across reviewers"


def test_onboard_idempotent(client: TestClient) -> None:
    r1 = client.post(
        "/api/calibrate/reviewers",
        json={"reviewer_id": "chris", "display_name": "Chris King"},
    )
    assert r1.status_code == 200
    assert r1.json()["already_existed"] is False

    r2 = client.post(
        "/api/calibrate/reviewers",
        json={"reviewer_id": "chris", "display_name": "Chris King"},
    )
    assert r2.status_code == 200
    assert r2.json()["already_existed"] is True


def test_next_returns_pair_with_consistent_swap(client: TestClient) -> None:
    client.post(
        "/api/calibrate/reviewers",
        json={"reviewer_id": "chris", "display_name": "Chris"},
    )
    r1 = client.get("/api/calibrate/next?reviewer_id=chris")
    r2 = client.get("/api/calibrate/next?reviewer_id=chris")
    assert r1.status_code == 200
    assert r2.status_code == 200
    body1 = r1.json()["pair"]
    body2 = r2.json()["pair"]
    assert body1["pair_id"] == body2["pair_id"]
    # Same display order both times — the swap is deterministic per (pair, reviewer).
    assert body1["display_a"] == body2["display_a"]
    assert body1["display_b"] == body2["display_b"]


def test_submit_label_removes_from_queue(client: TestClient) -> None:
    client.post(
        "/api/calibrate/reviewers",
        json={"reviewer_id": "chris", "display_name": "Chris"},
    )
    r1 = client.get("/api/calibrate/next?reviewer_id=chris").json()
    first_id = r1["pair"]["pair_id"]
    r_submit = client.post(
        "/api/calibrate/labels",
        json={
            "pair_id": first_id,
            "reviewer_id": "chris",
            "raw_label": "a",
            "time_ms": 1234,
        },
    )
    assert r_submit.status_code == 200
    assert r_submit.json()["accepted"] is True
    r2 = client.get("/api/calibrate/next?reviewer_id=chris").json()
    assert r2["pair"] is not None
    assert r2["pair"]["pair_id"] != first_id


def test_attention_check_counted_with_unswap(client: TestClient) -> None:
    # Onboard, then label only the attention check.
    client.post(
        "/api/calibrate/reviewers",
        json={"reviewer_id": "chris", "display_name": "Chris"},
    )
    # The attention check's correct answer is 'a' (response_a wins).
    # If the swap put the responses in opposite slots, the reviewer who
    # picks the *correct* answer on screen has shown_swapped=True and
    # their `a` becomes `b` after unswap. So to test we need to pick
    # *what the correct answer would be on screen* given the swap state.
    swap = decide_swap(pair_id="attn-1", reviewer_id="chris")
    raw = "b" if swap else "a"  # un-swap converts back to "a" either way
    r = client.post(
        "/api/calibrate/labels",
        json={"pair_id": "attn-1", "reviewer_id": "chris", "raw_label": raw},
    )
    assert r.status_code == 200
    progress = client.get("/api/calibrate/progress?reviewer_id=chris").json()
    assert progress["n_attention_passed"] == 1
    assert progress["n_attention_failed"] == 0


def test_attention_check_wrong_answer_counts_failure(client: TestClient) -> None:
    client.post(
        "/api/calibrate/reviewers",
        json={"reviewer_id": "chris", "display_name": "Chris"},
    )
    swap = decide_swap(pair_id="attn-1", reviewer_id="chris")
    # Pick the wrong on-screen answer.
    raw = "a" if swap else "b"
    r = client.post(
        "/api/calibrate/labels",
        json={"pair_id": "attn-1", "reviewer_id": "chris", "raw_label": raw},
    )
    assert r.status_code == 200
    progress = client.get("/api/calibrate/progress?reviewer_id=chris").json()
    assert progress["n_attention_failed"] == 1
    assert progress["n_attention_passed"] == 0


@pytest.mark.parametrize("bad_id", ["", "x" * 65, "Has Space", "UPPERCASE", "user@host", "---"])
def test_reviewer_id_rejected_on_label_submit(client: TestClient, bad_id: str) -> None:
    # Regression: reviewer_id was a bare str on LabelSubmission, so labels
    # could be attributed to ids the onboarding endpoint would reject. It now
    # shares the onboarding validator.
    r = client.post(
        "/api/calibrate/labels",
        json={"pair_id": "p1", "reviewer_id": bad_id, "raw_label": "a"},
    )
    assert r.status_code == 422


@pytest.mark.parametrize("bad_id", ["x" * 65, "Has Space", "UPPERCASE", "user@host", "---"])
def test_reviewer_id_rejected_on_next_and_progress(client: TestClient, bad_id: str) -> None:
    assert client.get("/api/calibrate/next", params={"reviewer_id": bad_id}).status_code == 422
    assert client.get("/api/calibrate/progress", params={"reviewer_id": bad_id}).status_code == 422


class _RaisingCalibrationStore(InMemoryCalibrationStore):
    def __init__(self, exc: Exception) -> None:
        super().__init__()
        self._exc = exc

    async def submit_label(self, **kwargs: object) -> str:  # type: ignore[override]
        raise self._exc


def _client_with(store: InMemoryCalibrationStore) -> TestClient:
    return TestClient(create_app(store=InMemoryStore(), calibration_store=store))


def test_label_submit_infra_error_returns_503() -> None:
    # Regression: a DB outage during submit was masked as a client 400
    # ("label rejected"), silently dropping the label. Infra failures must be
    # 503 so monitoring fires and clients can retry.
    with _client_with(_RaisingCalibrationStore(RuntimeError("pool exhausted"))) as tc:
        r = tc.post(
            "/api/calibrate/labels",
            json={"pair_id": "p1", "reviewer_id": "chris", "raw_label": "a"},
        )
    assert r.status_code == 503


def test_label_submit_bad_input_returns_400() -> None:
    with _client_with(_RaisingCalibrationStore(asyncpg.exceptions.DataError("bad uuid"))) as tc:
        r = tc.post(
            "/api/calibrate/labels",
            json={"pair_id": "not-a-uuid", "reviewer_id": "chris", "raw_label": "a"},
        )
    assert r.status_code == 400


def test_label_submit_unknown_pair_returns_404() -> None:
    exc = asyncpg.exceptions.ForeignKeyViolationError("no such pair")
    with _client_with(_RaisingCalibrationStore(exc)) as tc:
        r = tc.post(
            "/api/calibrate/labels",
            json={"pair_id": "p-missing", "reviewer_id": "chris", "raw_label": "a"},
        )
    assert r.status_code == 404


def test_rubric_endpoint_returns_markdown(client: TestClient) -> None:
    r = client.get("/api/calibrate/rubric")
    assert r.status_code == 200
    body = r.json()
    # Version is a content-hash stamp `v2+sha256:<hex>` when the rubric
    # file is readable (production / dev with the file checked out), or
    # falls back to `"v2"` when the file is missing.
    assert body["version"] == "v2" or body["version"].startswith("v2+sha256:")
    assert "Cascadia calibration rubric" in body["markdown"]
