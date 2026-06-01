"""Tests for the operator-auth surface (signup, verify, resend, login, session,
logout, roles).

Signup is double-opt-in: it issues NO session and emails a one-time link; the
account can't log in until that link is consumed via /verify. A FakeEmailSender
captures the link so tests can drive the full flow without real email.

Uses InMemoryAuthStore (no DB). Argon2 hashing runs for real (fast enough).
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from cascadia_dashboard.app import create_app
from cascadia_dashboard.auth import InMemoryAuthStore
from cascadia_dashboard.calibrate import InMemoryCalibrationStore
from cascadia_dashboard.store import InMemoryStore


class FakeEmailSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []  # (to_email, verify_url)

    async def send_verification(self, *, to_email: str, verify_url: str) -> None:
        self.sent.append((to_email, verify_url))

    def latest_token_for(self, email: str) -> str | None:
        for to, url in reversed(self.sent):
            if to.lower() == email.lower():
                qs = parse_qs(urlparse(url).query)
                return qs.get("token", [None])[0]
        return None


@pytest.fixture
def auth_store() -> InMemoryAuthStore:
    return InMemoryAuthStore()


@pytest.fixture
def email_sender() -> FakeEmailSender:
    return FakeEmailSender()


@pytest.fixture
def client(auth_store: InMemoryAuthStore, email_sender: FakeEmailSender) -> TestClient:
    app = create_app(
        store=InMemoryStore(),
        calibration_store=InMemoryCalibrationStore(),
        auth_store=auth_store,
        email_sender=email_sender,
    )
    with TestClient(app) as tc:
        yield tc


def _signup(client, email="ops@cascadia.dev", password="hunter2hunter", display_name="Ops"):
    body = {"email": email, "password": password}
    if display_name:
        body["display_name"] = display_name
    return client.post("/api/auth/signup", json=body)


def _verify(client, token):
    return client.post("/api/auth/verify", json={"token": token})


def _signup_verified(client, sender, email="ops@cascadia.dev", password="hunter2hunter"):
    r = _signup(client, email=email, password=password)
    assert r.status_code == 201, r.text
    tok = sender.latest_token_for(email)
    assert tok, "no verification email captured"
    v = _verify(client, tok)
    assert v.status_code == 200, v.text
    return v  # AuthResponse: {token, expires_at, user}


# --- signup is double opt-in -------------------------------------------------

def test_signup_issues_no_session_and_emails_a_link(client, email_sender):
    r = _signup(client)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email"] == "ops@cascadia.dev"
    assert body["verification_required"] is True
    assert "token" not in body  # NO session — sign-up isn't complete
    # A confirmation email was "sent" with a /verify?token=... link.
    assert email_sender.latest_token_for("ops@cascadia.dev")


# --- signup can be sealed (CASCADIA_SIGNUP_DISABLED) --------------------------

def test_sealed_instance_allows_bootstrap_then_closes(email_sender):
    store = InMemoryAuthStore()
    app = create_app(
        store=InMemoryStore(),
        calibration_store=InMemoryCalibrationStore(),
        auth_store=store,
        email_sender=email_sender,
        signup_disabled=True,
    )
    with TestClient(app) as client:
        # Bootstrap (first) account is allowed even when sealed — a fresh
        # instance can never lock itself out of creating its admin.
        first = _signup(client, email="admin@cascadia.dev")
        assert first.status_code == 201, first.text
        # Any subsequent signup is refused.
        second = _signup(client, email="intruder@evil.example")
        assert second.status_code == 403
        assert "closed" in second.json()["detail"].lower()


def test_open_instance_allows_second_signup(client):
    # Default (not sealed): multiple accounts are fine.
    assert _signup(client, email="a@cascadia.dev").status_code == 201
    assert _signup(client, email="b@cascadia.dev").status_code == 201


def test_login_before_verification_is_403(client):
    _signup(client)
    r = client.post(
        "/api/auth/login",
        json={"email": "ops@cascadia.dev", "password": "hunter2hunter"},
    )
    assert r.status_code == 403
    assert "not verified" in r.json()["detail"]


def test_verify_completes_signup_and_logs_in(client, email_sender):
    v = _signup_verified(client, email_sender)
    body = v.json()
    assert body["token"]
    assert body["user"]["email"] == "ops@cascadia.dev"
    # Session now validates, and login works post-verification.
    assert client.post("/api/auth/session", json={"token": body["token"]}).status_code == 200
    assert client.post(
        "/api/auth/login",
        json={"email": "ops@cascadia.dev", "password": "hunter2hunter"},
    ).status_code == 200


def test_verify_bad_token_400(client):
    assert _verify(client, "not-a-real-token").status_code == 400


def test_verify_token_is_single_use(client, email_sender):
    _signup(client)
    tok = email_sender.latest_token_for("ops@cascadia.dev")
    assert _verify(client, tok).status_code == 200
    assert _verify(client, tok).status_code == 400  # already consumed


def test_resend_is_generic_and_new_link_works(client, email_sender):
    _signup(client)
    r = client.post("/api/auth/resend-verification", json={"email": "ops@cascadia.dev"})
    assert r.status_code == 200 and r.json()["ok"] is True
    # The resent token verifies the account.
    tok = email_sender.latest_token_for("ops@cascadia.dev")
    assert _verify(client, tok).status_code == 200


def test_resend_unknown_email_is_generic_no_enumeration(client):
    r = client.post("/api/auth/resend-verification", json={"email": "ghost@x.dev"})
    assert r.status_code == 200 and r.json()["ok"] is True


# --- roles (now observed after verification) --------------------------------

def test_first_verified_account_is_admin_rest_operators(client, email_sender):
    first = _signup_verified(client, email_sender, email="boss@cascadia.dev")
    assert first.json()["user"]["role"] == "admin"
    second = _signup_verified(client, email_sender, email="grunt@cascadia.dev")
    assert second.json()["user"]["role"] == "operator"


def test_signup_cannot_self_assign_admin_via_body(client, email_sender):
    _signup_verified(client, email_sender, email="boss@cascadia.dev")  # admin
    client.post(
        "/api/auth/signup",
        json={"email": "sneaky@cascadia.dev", "password": "hunter2hunter", "role": "admin"},
    )
    tok = email_sender.latest_token_for("sneaky@cascadia.dev")
    assert _verify(client, tok).json()["user"]["role"] == "operator"


def test_admin_can_set_role_operator_cannot(client, email_sender):
    admin_token = _signup_verified(client, email_sender, email="boss@cascadia.dev").json()["token"]
    _signup_verified(client, email_sender, email="rev@cascadia.dev")
    op_token = _signup_verified(client, email_sender, email="op@cascadia.dev").json()["token"]

    forbidden = client.post(
        "/api/auth/role",
        json={"token": op_token, "email": "rev@cascadia.dev", "role": "reviewer"},
    )
    assert forbidden.status_code == 403

    ok = client.post(
        "/api/auth/role",
        json={"token": admin_token, "email": "rev@cascadia.dev", "role": "reviewer"},
    )
    assert ok.status_code == 200 and ok.json()["role"] == "reviewer"


def test_set_role_unknown_email_404(client, email_sender):
    admin_token = _signup_verified(client, email_sender, email="boss@cascadia.dev").json()["token"]
    r = client.post(
        "/api/auth/role",
        json={"token": admin_token, "email": "ghost@cascadia.dev", "role": "admin"},
    )
    assert r.status_code == 404


# --- login / session / logout (post-verification) ---------------------------

def test_signup_normalizes_email_case(client):
    r = _signup(client, email="MixedCase@Cascadia.DEV")
    assert r.status_code == 201
    assert r.json()["email"] == "mixedcase@cascadia.dev"


def test_signup_duplicate_email_conflicts(client):
    assert _signup(client).status_code == 201
    assert _signup(client, email="OPS@cascadia.dev").status_code == 409


def test_signup_rejects_bad_email(client):
    r = client.post("/api/auth/signup", json={"email": "nope", "password": "longenough1"})
    assert r.status_code == 422


def test_signup_rejects_short_password(client):
    r = client.post("/api/auth/signup", json={"email": "x@y.dev", "password": "short"})
    assert r.status_code == 422


def test_login_wrong_password_generic_401(client, email_sender):
    _signup_verified(client, email_sender)
    r = client.post(
        "/api/auth/login",
        json={"email": "ops@cascadia.dev", "password": "wrongpassword"},
    )
    assert r.status_code == 401 and r.json()["detail"] == "invalid email or password"


def test_login_unknown_email_same_generic_401(client):
    r = client.post(
        "/api/auth/login",
        json={"email": "ghost@cascadia.dev", "password": "whatever123"},
    )
    assert r.status_code == 401 and r.json()["detail"] == "invalid email or password"


def test_session_rejects_garbage_token(client):
    assert client.post("/api/auth/session", json={"token": "nope"}).status_code == 401


def test_logout_revokes_session(client, email_sender):
    token = _signup_verified(client, email_sender).json()["token"]
    assert client.post("/api/auth/session", json={"token": token}).status_code == 200
    out = client.post("/api/auth/logout", json={"token": token})
    assert out.status_code == 200 and out.json()["revoked"] is True
    assert client.post("/api/auth/session", json={"token": token}).status_code == 401


def test_password_hash_is_not_plaintext(auth_store):
    import asyncio

    from cascadia_dashboard.auth.security import hash_password

    async def go():
        await auth_store.create_user(
            user_id="u1", email="x@y.dev", password_hash=hash_password("supersecret1"), display_name=None
        )
        u = await auth_store.get_user_by_email("x@y.dev")
        assert u is not None
        assert "supersecret1" not in u.password_hash
        assert u.password_hash.startswith("$argon2")
        assert u.email_verified is False  # created unverified

    asyncio.run(go())
