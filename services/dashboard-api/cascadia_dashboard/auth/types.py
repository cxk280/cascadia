"""Pydantic wire types for the operator-auth surface (email + password).

Validation rules live here as the single source of truth so the signup,
login, and session endpoints agree on what an acceptable email / password
looks like.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Role = Literal["operator", "admin", "reviewer"]

# Email: a deliberately *moderate* shape check, not RFC 5322. We only need to
# reject obvious junk before it reaches the store — the address isn't used for
# delivery, it's a login handle. `something@something.tld` with no spaces.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
EMAIL_MAX_LEN = 254  # RFC-practical maximum.

# Password policy: a length floor (NIST-style — length over composition rules)
# and a ceiling. The ceiling bounds Argon2 hashing cost from a hostile
# megabyte-long password, and keeps us clear of any per-algorithm input limits.
PASSWORD_MIN_LEN = 8
PASSWORD_MAX_LEN = 128

DISPLAY_NAME_MAX_LEN = 120
_HTML_TAG = re.compile(r"<[^>]+>")


def normalize_email(email: str) -> str:
    """Canonical form used for storage and lookup: trimmed + lowercased.

    Applied identically on signup and login so `Chris@X.com` and
    `chris@x.com` resolve to the same account and can't both be registered.
    """
    return email.strip().lower()


def validate_email(email: str) -> str:
    e = normalize_email(email)
    if not (3 <= len(e) <= EMAIL_MAX_LEN):
        raise ValueError(f"email must be 3-{EMAIL_MAX_LEN} characters")
    if not _EMAIL_RE.fullmatch(e):
        raise ValueError("email must look like name@domain.tld")
    return e


def validate_password(pw: str) -> str:
    # Note: no .strip() — leading/trailing spaces are legitimate password
    # characters. We validate length on the raw string.
    if not (PASSWORD_MIN_LEN <= len(pw) <= PASSWORD_MAX_LEN):
        raise ValueError(
            f"password must be {PASSWORD_MIN_LEN}-{PASSWORD_MAX_LEN} characters"
        )
    return pw


class SignupRequest(BaseModel):
    email: str
    password: str
    display_name: str | None = Field(default=None, max_length=DISPLAY_NAME_MAX_LEN)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return validate_email(v)

    @field_validator("password")
    @classmethod
    def _password(cls, v: str) -> str:
        return validate_password(v)

    @field_validator("display_name")
    @classmethod
    def _display_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if _HTML_TAG.search(v):
            raise ValueError("display_name must not contain HTML tags")
        return v


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        # Normalize but don't hard-reject shape on login — an address that
        # can't pass signup validation simply won't match a stored row. We
        # only lowercase/trim so lookups are case-insensitive.
        return normalize_email(v)


class TokenRequest(BaseModel):
    """Body for /session and /logout — the opaque token the Next.js layer
    pulled from the httpOnly cookie. Sent in the POST body (not a query
    string) so it never lands in an access log."""

    token: str = Field(min_length=1, max_length=512)


class SessionUser(BaseModel):
    user_id: str
    email: str
    display_name: str | None = None
    role: Role = "operator"


class SetRoleRequest(BaseModel):
    """Admin-only: change another account's role. `token` is the caller's
    session token (must belong to an admin); `email` identifies the target."""

    token: str = Field(min_length=1, max_length=512)
    email: str
    role: Role

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return normalize_email(v)


class AuthResponse(BaseModel):
    """Returned by signup + login. The `token` is consumed by the Next.js
    route handler, which stores it in an httpOnly cookie and strips it before
    anything reaches the browser JS."""

    token: str
    expires_at: datetime
    user: SessionUser


class SessionResponse(BaseModel):
    """Returned by /session. Deliberately carries NO token — it only confirms
    the presented one is live and surfaces who it belongs to."""

    user: SessionUser
    expires_at: datetime


class LogoutAck(BaseModel):
    revoked: bool
