"""FastAPI route registration for the operator-auth surface.

  POST /api/auth/signup   — create an account, return a fresh session
  POST /api/auth/login    — verify credentials, return a fresh session
  POST /api/auth/session  — validate a presented token, return its owner
  POST /api/auth/logout   — revoke a presented token

These are server-to-server endpoints: the browser never calls them directly.
The Next.js dashboard's route handlers (under app/api/auth/*) forward to here
and own the httpOnly session cookie, so the raw token never reaches browser
JS and this service can stay off the public network — same posture as the
calibration write surface.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Callable

from fastapi import APIRouter, FastAPI, HTTPException, Request, status

from cascadia_dashboard.auth.security import (
    generate_session_token,
    hash_password,
    hash_token,
    needs_rehash,
    verify_password,
)
from cascadia_dashboard.auth.store import (
    AuthStore,
    DuplicateEmailError,
    SESSION_TTL,
)
from cascadia_dashboard.auth.types import (
    AuthResponse,
    LoginRequest,
    LogoutAck,
    SessionResponse,
    SessionUser,
    SignupRequest,
    TokenRequest,
)

log = logging.getLogger(__name__)

# A pre-computed Argon2 hash of a throwaway value. On a login for an unknown
# email we verify the supplied password against THIS so the failure path costs
# the same as a real mismatch — closing the timing side-channel that would
# otherwise let an attacker enumerate which emails are registered.
_DUMMY_HASH = hash_password("cascadia-timing-equalizer")


async def _issue_session(
    store: AuthStore, *, user_id: str, request: Request
) -> tuple[str, datetime]:
    """Mint a new opaque session for `user_id`. Returns (raw_token, expires_at).

    Only the SHA-256 of the token is persisted; the raw token is returned to
    the caller (the Next.js layer) to set as an httpOnly cookie.
    """
    token = generate_session_token()
    expires_at = datetime.now(timezone.utc) + SESSION_TTL
    user_agent = request.headers.get("user-agent")
    if user_agent is not None:
        user_agent = user_agent[:512]  # bound an attacker-controlled header
    await store.create_session(
        session_id=str(uuid.uuid4()),
        user_id=user_id,
        token_sha256=hash_token(token),
        expires_at=expires_at,
        user_agent=user_agent,
    )
    return token, expires_at


def attach_auth_routes(app: FastAPI, get_store: Callable[[], AuthStore]) -> None:
    router = APIRouter(prefix="/api/auth", tags=["auth"])

    @router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
    async def signup(req: SignupRequest, request: Request) -> AuthResponse:
        store = get_store()
        user_id = str(uuid.uuid4())
        password_hash = hash_password(req.password)
        try:
            await store.create_user(
                user_id=user_id,
                email=req.email,
                password_hash=password_hash,
                display_name=req.display_name,
            )
        except DuplicateEmailError:
            # 409, not 401 — the client asked to create something that exists.
            # We DO reveal "email taken" here (unlike login, which stays
            # generic): signup enumeration is unavoidable for any product that
            # tells a user "that address already has an account", and the
            # alternative (silently succeeding) is a worse foot-gun.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="an account with this email already exists",
            )
        token, expires_at = await _issue_session(store, user_id=user_id, request=request)
        return AuthResponse(
            token=token,
            expires_at=expires_at,
            user=SessionUser(
                user_id=user_id, email=req.email, display_name=req.display_name
            ),
        )

    @router.post("/login", response_model=AuthResponse)
    async def login(req: LoginRequest, request: Request) -> AuthResponse:
        store = get_store()
        user = await store.get_user_by_email(req.email)
        if user is None:
            # Spend the same work as a real verify so timing doesn't leak
            # whether the email exists, then fail with the SAME generic error.
            verify_password(_DUMMY_HASH, req.password)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid email or password",
            )
        if not verify_password(user.password_hash, req.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid email or password",
            )
        # Transparent hash upgrade: if the stored hash predates a params bump,
        # re-hash now that we have the plaintext in hand.
        if needs_rehash(user.password_hash):
            await store.update_password_hash(user.user_id, hash_password(req.password))
        await store.update_last_login(user.user_id)
        token, expires_at = await _issue_session(
            store, user_id=user.user_id, request=request
        )
        return AuthResponse(
            token=token,
            expires_at=expires_at,
            user=SessionUser(
                user_id=user.user_id, email=user.email, display_name=user.display_name
            ),
        )

    @router.post("/session", response_model=SessionResponse)
    async def session(req: TokenRequest) -> SessionResponse:
        active = await get_store().get_active_session(hash_token(req.token))
        if active is None:
            # Covers absent, expired, AND revoked — the store only returns
            # live sessions. Generic 401; never distinguish the reason.
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="session invalid or expired",
            )
        return SessionResponse(
            user=SessionUser(
                user_id=active.user_id,
                email=active.email,
                display_name=active.display_name,
            ),
            expires_at=active.expires_at,
        )

    @router.post("/logout", response_model=LogoutAck)
    async def logout(req: TokenRequest) -> LogoutAck:
        # Idempotent — logging out an already-dead token is a no-op success.
        revoked = await get_store().revoke_session(hash_token(req.token))
        return LogoutAck(revoked=revoked)

    app.include_router(router)
