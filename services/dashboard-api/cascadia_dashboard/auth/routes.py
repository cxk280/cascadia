"""FastAPI route registration for the operator-auth surface.

  POST /api/auth/signup              — create an UNVERIFIED account + email a link
  POST /api/auth/verify              — consume an email link, verify, return a session
  POST /api/auth/resend-verification — re-send the confirmation email
  POST /api/auth/login               — verify credentials (verified only), session
  POST /api/auth/session             — validate a presented token, return its owner
  POST /api/auth/logout              — revoke a presented token

These are server-to-server endpoints: the browser never calls them directly.
The Next.js dashboard's route handlers (under app/api/auth/*) forward to here
and own the httpOnly session cookie, so the raw token never reaches browser
JS and this service can stay off the public network — same posture as the
calibration write surface.

Signup is double-opt-in: it issues NO session, just emails a one-time link.
The account can't log in until that link is used (including the first/admin
account — no exception).
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Callable

from fastapi import APIRouter, FastAPI, HTTPException, Request, status

from cascadia_dashboard.auth.email import EmailSender, email_sender_from_env
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
    VERIFICATION_TTL,
)
from cascadia_dashboard.auth.types import (
    AuthResponse,
    GenericAck,
    LoginRequest,
    LogoutAck,
    ResendRequest,
    SessionResponse,
    SessionUser,
    SetRoleRequest,
    SignupAck,
    SignupRequest,
    TokenRequest,
    VerifyRequest,
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


async def _send_verification(
    store: AuthStore, sender: EmailSender, dashboard_url: str, *, user_id: str, email: str
) -> None:
    """Mint a one-time verification token, persist its hash, and email the link.
    Only the SHA-256 is stored; the raw token travels in the link."""
    token = generate_session_token()
    expires_at = datetime.now(timezone.utc) + VERIFICATION_TTL
    await store.create_email_verification(
        id=str(uuid.uuid4()),
        user_id=user_id,
        token_sha256=hash_token(token),
        expires_at=expires_at,
    )
    verify_url = f"{dashboard_url.rstrip('/')}/verify?token={token}"
    await sender.send_verification(to_email=email, verify_url=verify_url)


def attach_auth_routes(
    app: FastAPI,
    get_store: Callable[[], AuthStore],
    *,
    email_sender: EmailSender | None = None,
    dashboard_url: str | None = None,
) -> None:
    router = APIRouter(prefix="/api/auth", tags=["auth"])
    sender = email_sender or email_sender_from_env()
    dash_url = dashboard_url or os.environ.get(
        "CASCADIA_DASHBOARD_URL", "http://localhost:3000"
    )

    @router.post("/signup", response_model=SignupAck, status_code=status.HTTP_201_CREATED)
    async def signup(req: SignupRequest) -> SignupAck:
        store = get_store()
        user_id = str(uuid.uuid4())
        password_hash = hash_password(req.password)
        # Bootstrap: the FIRST account becomes admin (the methodology owner);
        # everyone after is an operator. Role is never taken from the request —
        # that would be a trivial privilege escalation. An admin promotes others
        # via /api/auth/role.
        role = "admin" if await store.count_users() == 0 else "operator"
        try:
            await store.create_user(
                user_id=user_id,
                email=req.email,
                password_hash=password_hash,
                display_name=req.display_name,
                role=role,
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
        # Double opt-in: NO session is issued. Email the confirmation link; the
        # account stays unverified (can't log in) until it's used.
        await _send_verification(
            store, sender, dash_url, user_id=user_id, email=req.email
        )
        return SignupAck(email=req.email)

    @router.post("/verify", response_model=AuthResponse)
    async def verify(req: VerifyRequest, request: Request) -> AuthResponse:
        verified = await get_store().consume_email_verification(hash_token(req.token))
        if verified is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="verification link is invalid, expired, or already used",
            )
        # Verified — sign-up is now complete; log them in.
        token, expires_at = await _issue_session(
            get_store(), user_id=verified.user_id, request=request
        )
        return AuthResponse(
            token=token,
            expires_at=expires_at,
            user=SessionUser(
                user_id=verified.user_id,
                email=verified.email,
                display_name=verified.display_name,
                role=verified.role,
            ),
        )

    @router.post("/resend-verification", response_model=GenericAck)
    async def resend_verification(req: ResendRequest) -> GenericAck:
        store = get_store()
        user = await store.get_user_by_email(req.email)
        # Only act for a real, still-unverified account; ALWAYS return the same
        # generic ack so this can't be used to probe which emails exist.
        if user is not None and not user.email_verified:
            await _send_verification(
                store, sender, dash_url, user_id=user.user_id, email=user.email
            )
        return GenericAck()

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
        if not user.email_verified:
            # Correct password but unconfirmed. We surface this specifically (it
            # reveals the account exists, same as signup's 409) because the user
            # needs to know to check their inbox / resend.
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="email not verified — check your inbox for the confirmation link",
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
                user_id=user.user_id,
                email=user.email,
                display_name=user.display_name,
                role=user.role,
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
                role=active.role,
            ),
            expires_at=active.expires_at,
        )

    @router.post("/logout", response_model=LogoutAck)
    async def logout(req: TokenRequest) -> LogoutAck:
        # Idempotent — logging out an already-dead token is a no-op success.
        revoked = await get_store().revoke_session(hash_token(req.token))
        return LogoutAck(revoked=revoked)

    @router.post("/role", response_model=SessionUser)
    async def set_role(req: SetRoleRequest) -> SessionUser:
        # Admin-only. The caller proves they're an admin with their own live
        # session token; we never trust a client-supplied "I am admin" claim.
        store = get_store()
        caller = await store.get_active_session(hash_token(req.token))
        if caller is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="session invalid or expired",
            )
        if caller.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="admin role required",
            )
        # Guard against an admin demoting the last admin and locking everyone
        # out of calibration/role management is out of scope here; the bootstrap
        # admin can always be re-promoted directly in the DB if needed.
        ok = await store.set_role(req.email, req.role)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="no account with that email",
            )
        updated = await store.get_user_by_email(req.email)
        assert updated is not None  # set_role returned True
        return SessionUser(
            user_id=updated.user_id,
            email=updated.email,
            display_name=updated.display_name,
            role=updated.role,
        )

    app.include_router(router)
