"""Repository for operator-auth state (users + opaque sessions).

Mirrors the calibration store's shape: a `Protocol` contract, an
asyncpg-backed implementation for production (sharing the read-side pool),
and an in-memory fake for tests so no DB is needed.

Session validation is a single indexed read: the live/expired/revoked
decision is expressed in SQL so the dashboard's per-request gate stays cheap.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable

import asyncpg

# Absolute session lifetime. Matches the 30-day reviewer-cookie horizon the
# calibration flow already uses. Absolute (not sliding) keeps the model
# simple — a session is good for 30 days from issue, then the user logs in
# again. Logout revokes immediately regardless.
SESSION_TTL = timedelta(days=30)

# How long an email-confirmation link stays valid.
VERIFICATION_TTL = timedelta(hours=24)


class DuplicateEmailError(Exception):
    """Raised by `create_user` when the email is already registered."""


@dataclass(frozen=True)
class StoredUser:
    user_id: str
    email: str
    password_hash: str
    display_name: str | None
    role: str = "operator"
    email_verified: bool = False


@dataclass(frozen=True)
class VerifiedUser:
    """The user row returned when a verification token is successfully
    consumed — enough to mint a session."""

    user_id: str
    email: str
    display_name: str | None
    role: str


@dataclass(frozen=True)
class ActiveSession:
    """A session that is present, unrevoked, and unexpired, joined to its
    owning user. Returned only for live sessions — the store filters dead
    ones out in the query."""

    user_id: str
    email: str
    display_name: str | None
    role: str
    expires_at: datetime


@runtime_checkable
class AuthStore(Protocol):
    async def create_user(
        self,
        *,
        user_id: str,
        email: str,
        password_hash: str,
        display_name: str | None,
        role: str = "operator",
    ) -> None: ...
    async def get_user_by_email(self, email: str) -> "StoredUser | None": ...
    async def count_users(self) -> int: ...
    async def set_role(self, email: str, role: str) -> bool: ...
    async def create_email_verification(
        self, *, id: str, user_id: str, token_sha256: str, expires_at: datetime
    ) -> None: ...
    async def consume_email_verification(
        self, token_sha256: str
    ) -> "VerifiedUser | None": ...
    async def update_last_login(self, user_id: str) -> None: ...
    async def update_password_hash(self, user_id: str, password_hash: str) -> None: ...
    async def create_session(
        self,
        *,
        session_id: str,
        user_id: str,
        token_sha256: str,
        expires_at: datetime,
        user_agent: str | None,
    ) -> None: ...
    async def get_active_session(self, token_sha256: str) -> "ActiveSession | None": ...
    async def revoke_session(self, token_sha256: str) -> bool: ...


class AsyncpgAuthStore(AuthStore):
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create_user(
        self,
        *,
        user_id: str,
        email: str,
        password_hash: str,
        display_name: str | None,
        role: str = "operator",
    ) -> None:
        sql = """
            INSERT INTO auth_users (user_id, email, password_hash, display_name, role)
            VALUES ($1, $2, $3, $4, $5)
        """
        try:
            await self._pool.execute(
                sql, user_id, email, password_hash, display_name, role
            )
        except asyncpg.exceptions.UniqueViolationError as exc:
            # The LOWER(email) unique index (or the PK) fired. Either way the
            # caller-facing meaning is "this email is taken".
            raise DuplicateEmailError(email) from exc

    async def get_user_by_email(self, email: str) -> StoredUser | None:
        sql = """
            SELECT user_id, email, password_hash, display_name, role, email_verified
              FROM auth_users
             WHERE LOWER(email) = LOWER($1)
             LIMIT 1
        """
        row = await self._pool.fetchrow(sql, email)
        if row is None:
            return None
        return StoredUser(
            user_id=str(row["user_id"]),
            email=row["email"],
            password_hash=row["password_hash"],
            display_name=row["display_name"],
            role=row["role"],
            email_verified=row["email_verified"],
        )

    async def create_email_verification(
        self, *, id: str, user_id: str, token_sha256: str, expires_at: datetime
    ) -> None:
        await self._pool.execute(
            "INSERT INTO auth_email_verifications "
            "(id, user_id, token_sha256, expires_at) VALUES ($1, $2, $3, $4)",
            id,
            user_id,
            token_sha256,
            expires_at,
        )

    async def consume_email_verification(
        self, token_sha256: str
    ) -> VerifiedUser | None:
        # One statement: spend the (unconsumed, unexpired) token AND flip the
        # user's email_verified, returning the user. No row -> token was
        # absent/expired/already-used.
        sql = """
            WITH v AS (
                UPDATE auth_email_verifications
                   SET consumed_at = NOW()
                 WHERE token_sha256 = $1
                   AND consumed_at IS NULL
                   AND expires_at > NOW()
                RETURNING user_id
            ), u AS (
                UPDATE auth_users
                   SET email_verified = true
                 WHERE user_id = (SELECT user_id FROM v)
                RETURNING user_id, email, display_name, role
            )
            SELECT user_id, email, display_name, role FROM u
        """
        row = await self._pool.fetchrow(sql, token_sha256)
        if row is None:
            return None
        return VerifiedUser(
            user_id=str(row["user_id"]),
            email=row["email"],
            display_name=row["display_name"],
            role=row["role"],
        )

    async def count_users(self) -> int:
        row = await self._pool.fetchrow("SELECT COUNT(*) AS n FROM auth_users")
        return int(row["n"]) if row else 0

    async def set_role(self, email: str, role: str) -> bool:
        row = await self._pool.fetchrow(
            "UPDATE auth_users SET role = $2 WHERE LOWER(email) = LOWER($1) "
            "RETURNING user_id",
            email,
            role,
        )
        return row is not None

    async def update_last_login(self, user_id: str) -> None:
        await self._pool.execute(
            "UPDATE auth_users SET last_login_at = NOW() WHERE user_id = $1", user_id
        )

    async def update_password_hash(self, user_id: str, password_hash: str) -> None:
        await self._pool.execute(
            "UPDATE auth_users SET password_hash = $2 WHERE user_id = $1",
            user_id,
            password_hash,
        )

    async def create_session(
        self,
        *,
        session_id: str,
        user_id: str,
        token_sha256: str,
        expires_at: datetime,
        user_agent: str | None,
    ) -> None:
        sql = """
            INSERT INTO auth_sessions
                (session_id, user_id, token_sha256, expires_at, user_agent)
            VALUES ($1, $2, $3, $4, $5)
        """
        await self._pool.execute(
            sql, session_id, user_id, token_sha256, expires_at, user_agent
        )

    async def get_active_session(self, token_sha256: str) -> ActiveSession | None:
        # Liveness is decided in SQL (unrevoked + unexpired) so validation is
        # one indexed read with no app-side clock branching.
        sql = """
            SELECT s.user_id, s.expires_at, u.email, u.display_name, u.role
              FROM auth_sessions s
              JOIN auth_users    u ON u.user_id = s.user_id
             WHERE s.token_sha256 = $1
               AND s.revoked_at IS NULL
               AND s.expires_at > NOW()
             LIMIT 1
        """
        row = await self._pool.fetchrow(sql, token_sha256)
        if row is None:
            return None
        return ActiveSession(
            user_id=str(row["user_id"]),
            email=row["email"],
            display_name=row["display_name"],
            role=row["role"],
            expires_at=row["expires_at"],
        )

    async def revoke_session(self, token_sha256: str) -> bool:
        # Idempotent: only flips a row that isn't already revoked. Returns
        # whether this call was the one that revoked it.
        row = await self._pool.fetchrow(
            """
            UPDATE auth_sessions
               SET revoked_at = NOW()
             WHERE token_sha256 = $1
               AND revoked_at IS NULL
            RETURNING session_id
            """,
            token_sha256,
        )
        return row is not None


class InMemoryAuthStore(AuthStore):
    """Test fake. Holds users + sessions in dicts."""

    def __init__(self) -> None:
        self._users: dict[str, StoredUser] = {}  # keyed by user_id
        self._email_index: dict[str, str] = {}  # lower(email) -> user_id
        # token_sha256 -> session dict
        self._sessions: dict[str, dict] = {}
        # token_sha256 -> verification dict
        self._verifications: dict[str, dict] = {}

    async def create_user(
        self,
        *,
        user_id: str,
        email: str,
        password_hash: str,
        display_name: str | None,
        role: str = "operator",
    ) -> None:
        if email.lower() in self._email_index:
            raise DuplicateEmailError(email)
        self._users[user_id] = StoredUser(
            user_id=user_id,
            email=email,
            password_hash=password_hash,
            display_name=display_name,
            role=role,
        )
        self._email_index[email.lower()] = user_id

    async def get_user_by_email(self, email: str) -> StoredUser | None:
        user_id = self._email_index.get(email.lower())
        return self._users.get(user_id) if user_id else None

    async def count_users(self) -> int:
        return len(self._users)

    async def set_role(self, email: str, role: str) -> bool:
        user_id = self._email_index.get(email.lower())
        if user_id is None:
            return False
        u = self._users[user_id]
        self._users[user_id] = StoredUser(
            user_id=u.user_id,
            email=u.email,
            password_hash=u.password_hash,
            display_name=u.display_name,
            role=role,
        )
        return True

    async def update_last_login(self, user_id: str) -> None:
        # No observable field in the fake; the call must just not error.
        return None

    async def update_password_hash(self, user_id: str, password_hash: str) -> None:
        u = self._users.get(user_id)
        if u is not None:
            self._users[user_id] = StoredUser(
                user_id=u.user_id,
                email=u.email,
                password_hash=password_hash,
                display_name=u.display_name,
                role=u.role,
                email_verified=u.email_verified,
            )

    async def create_email_verification(
        self, *, id: str, user_id: str, token_sha256: str, expires_at: datetime
    ) -> None:
        self._verifications[token_sha256] = {
            "id": id,
            "user_id": user_id,
            "expires_at": expires_at,
            "consumed": False,
        }

    async def consume_email_verification(
        self, token_sha256: str
    ) -> VerifiedUser | None:
        v = self._verifications.get(token_sha256)
        if v is None or v["consumed"]:
            return None
        if v["expires_at"] <= datetime.now(timezone.utc):
            return None
        v["consumed"] = True
        u = self._users.get(v["user_id"])
        if u is None:
            return None
        self._users[u.user_id] = StoredUser(
            user_id=u.user_id,
            email=u.email,
            password_hash=u.password_hash,
            display_name=u.display_name,
            role=u.role,
            email_verified=True,
        )
        return VerifiedUser(
            user_id=u.user_id, email=u.email, display_name=u.display_name, role=u.role
        )

    async def create_session(
        self,
        *,
        session_id: str,
        user_id: str,
        token_sha256: str,
        expires_at: datetime,
        user_agent: str | None,
    ) -> None:
        self._sessions[token_sha256] = {
            "session_id": session_id,
            "user_id": user_id,
            "expires_at": expires_at,
            "revoked": False,
        }

    async def get_active_session(self, token_sha256: str) -> ActiveSession | None:
        s = self._sessions.get(token_sha256)
        if s is None or s["revoked"]:
            return None
        if s["expires_at"] <= datetime.now(timezone.utc):
            return None
        user = self._users.get(s["user_id"])
        if user is None:
            return None
        return ActiveSession(
            user_id=user.user_id,
            email=user.email,
            display_name=user.display_name,
            role=user.role,
            expires_at=s["expires_at"],
        )

    async def revoke_session(self, token_sha256: str) -> bool:
        s = self._sessions.get(token_sha256)
        if s is None or s["revoked"]:
            return False
        s["revoked"] = True
        return True
