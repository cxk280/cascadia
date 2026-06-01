"""Operator authentication — email + password accounts and opaque sessions.

Extends the dashboard-api with the auth write/validate surface:

  POST /api/auth/signup   — create an account (idempotent-safe), return a session
  POST /api/auth/login    — verify credentials, return a session
  POST /api/auth/session  — validate a presented token, return its owner
  POST /api/auth/logout   — revoke a presented token

Passwords are Argon2id; sessions are server-side opaque tokens (only the
SHA-256 is persisted). See PLAN.md §9 (2026-06-01) for why this is roll-our-own
rather than OAuth, and opaque sessions rather than JWT.
"""

from cascadia_dashboard.auth.routes import attach_auth_routes
from cascadia_dashboard.auth.store import (
    AsyncpgAuthStore,
    AuthStore,
    DuplicateEmailError,
    InMemoryAuthStore,
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

__all__ = [
    "AsyncpgAuthStore",
    "AuthStore",
    "AuthResponse",
    "DuplicateEmailError",
    "InMemoryAuthStore",
    "LoginRequest",
    "LogoutAck",
    "SessionResponse",
    "SessionUser",
    "SignupRequest",
    "TokenRequest",
    "attach_auth_routes",
]
