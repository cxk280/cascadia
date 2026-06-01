"""Tests for the operator-auth surface (signup, login, session, logout).

Uses `InMemoryAuthStore` so no DB is needed. Argon2 hashing runs for real
(it's fast enough), so these also exercise the hash/verify round-trip.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cascadia_dashboard.app import create_app
from cascadia_dashboard.auth import InMemoryAuthStore
from cascadia_dashboard.calibrate import InMemoryCalibrationStore
from cascadia_dashboard.store import InMemoryStore


@pytest.fixture
def auth_store() -> InMemoryAuthStore:
    return InMemoryAuthStore()


@pytest.fixture
def client(auth_store: InMemoryAuthStore) -> TestClient:
    app = create_app(
        store=InMemoryStore(),
        calibration_store=InMemoryCalibrationStore(),
        auth_store=auth_store,
    )
    with TestClient(app) as tc:
        yield tc


def _signup(client: TestClient, email="ops@cascadia.dev", password="hunter2hunter"):
    return client.post(
        "/api/auth/signup",
        json={"email": email, "password": password, "display_name": "Ops"},
    )


def test_first_signup_is_admin_rest_are_operators(client: TestClient) -> None:
    first = _signup(client, email="boss@cascadia.dev")
    assert first.status_code == 201
    assert first.json()["user"]["role"] == "admin"
    second = _signup(client, email="grunt@cascadia.dev")
    assert second.status_code == 201
    assert second.json()["user"]["role"] == "operator"


def test_signup_cannot_self_assign_admin_via_body(client: TestClient) -> None:
    # Even if a client sends role=admin, it's ignored — the 2nd signup is an
    # operator regardless of the request body.
    _signup(client, email="boss@cascadia.dev")
    r = client.post(
        "/api/auth/signup",
        json={
            "email": "sneaky@cascadia.dev",
            "password": "hunter2hunter",
            "role": "admin",
        },
    )
    assert r.status_code == 201
    assert r.json()["user"]["role"] == "operator"


def test_admin_can_set_role_operator_cannot(client: TestClient) -> None:
    admin_token = _signup(client, email="boss@cascadia.dev").json()["token"]
    _signup(client, email="rev@cascadia.dev")  # operator
    op_token = _signup(client, email="op@cascadia.dev").json()["token"]

    # Operator may not change roles.
    forbidden = client.post(
        "/api/auth/role",
        json={"token": op_token, "email": "rev@cascadia.dev", "role": "reviewer"},
    )
    assert forbidden.status_code == 403

    # Admin promotes the reviewer.
    ok = client.post(
        "/api/auth/role",
        json={"token": admin_token, "email": "rev@cascadia.dev", "role": "reviewer"},
    )
    assert ok.status_code == 200
    assert ok.json()["role"] == "reviewer"

    # And the session for that user now reports reviewer.
    rev_login = client.post(
        "/api/auth/login",
        json={"email": "rev@cascadia.dev", "password": "hunter2hunter"},
    )
    assert rev_login.json()["user"]["role"] == "reviewer"


def test_set_role_unknown_email_404(client: TestClient) -> None:
    admin_token = _signup(client, email="boss@cascadia.dev").json()["token"]
    r = client.post(
        "/api/auth/role",
        json={"token": admin_token, "email": "ghost@cascadia.dev", "role": "admin"},
    )
    assert r.status_code == 404


def test_signup_creates_account_and_session(client: TestClient) -> None:
    r = _signup(client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["user"]["email"] == "ops@cascadia.dev"
    assert body["user"]["display_name"] == "Ops"
    assert body["user"]["role"] == "admin"  # first account
    assert body["token"]
    # The freshly issued token validates.
    s = client.post("/api/auth/session", json={"token": body["token"]})
    assert s.status_code == 200
    assert s.json()["user"]["email"] == "ops@cascadia.dev"


def test_signup_normalizes_email_case(client: TestClient) -> None:
    r = _signup(client, email="MixedCase@Cascadia.DEV")
    assert r.status_code == 201
    assert r.json()["user"]["email"] == "mixedcase@cascadia.dev"


def test_signup_duplicate_email_conflicts(client: TestClient) -> None:
    assert _signup(client).status_code == 201
    # Same email, different case → still a conflict (case-insensitive).
    dup = _signup(client, email="OPS@cascadia.dev")
    assert dup.status_code == 409
    assert "already exists" in dup.json()["detail"]


def test_signup_rejects_bad_email(client: TestClient) -> None:
    r = client.post(
        "/api/auth/signup", json={"email": "not-an-email", "password": "longenough1"}
    )
    assert r.status_code == 422


def test_signup_rejects_short_password(client: TestClient) -> None:
    r = client.post(
        "/api/auth/signup", json={"email": "x@y.dev", "password": "short"}
    )
    assert r.status_code == 422


def test_login_succeeds_with_correct_password(client: TestClient) -> None:
    _signup(client)
    r = client.post(
        "/api/auth/login",
        json={"email": "ops@cascadia.dev", "password": "hunter2hunter"},
    )
    assert r.status_code == 200, r.text
    assert client.post(
        "/api/auth/session", json={"token": r.json()["token"]}
    ).status_code == 200


def test_login_wrong_password_is_generic_401(client: TestClient) -> None:
    _signup(client)
    r = client.post(
        "/api/auth/login",
        json={"email": "ops@cascadia.dev", "password": "wrongpassword"},
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid email or password"


def test_login_unknown_email_is_same_generic_401(client: TestClient) -> None:
    # Unknown email must return the SAME response as a wrong password so the
    # endpoint doesn't leak which emails are registered.
    r = client.post(
        "/api/auth/login",
        json={"email": "ghost@cascadia.dev", "password": "whatever123"},
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid email or password"


def test_login_is_case_insensitive_on_email(client: TestClient) -> None:
    _signup(client)
    r = client.post(
        "/api/auth/login",
        json={"email": "OPS@CASCADIA.DEV", "password": "hunter2hunter"},
    )
    assert r.status_code == 200


def test_session_rejects_garbage_token(client: TestClient) -> None:
    r = client.post("/api/auth/session", json={"token": "not-a-real-token"})
    assert r.status_code == 401


def test_logout_revokes_session(client: TestClient) -> None:
    token = _signup(client).json()["token"]
    # Live before logout.
    assert client.post("/api/auth/session", json={"token": token}).status_code == 200
    out = client.post("/api/auth/logout", json={"token": token})
    assert out.status_code == 200
    assert out.json()["revoked"] is True
    # Dead after logout.
    assert client.post("/api/auth/session", json={"token": token}).status_code == 401


def test_logout_is_idempotent(client: TestClient) -> None:
    token = _signup(client).json()["token"]
    client.post("/api/auth/logout", json={"token": token})
    again = client.post("/api/auth/logout", json={"token": token})
    assert again.status_code == 200
    assert again.json()["revoked"] is False


def test_password_hash_is_not_plaintext(auth_store: InMemoryAuthStore) -> None:
    # Defense-in-depth: assert we never store the raw password.
    import asyncio

    from cascadia_dashboard.auth.security import hash_password

    async def go() -> None:
        await auth_store.create_user(
            user_id="u1",
            email="x@y.dev",
            password_hash=hash_password("supersecret1"),
            display_name=None,
        )
        u = await auth_store.get_user_by_email("x@y.dev")
        assert u is not None
        assert "supersecret1" not in u.password_hash
        assert u.password_hash.startswith("$argon2")

    asyncio.run(go())
