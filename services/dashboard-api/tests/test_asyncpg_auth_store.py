"""AsyncpgAuthStore unit tests with a stubbed asyncpg pool.

Same approach as test_asyncpg_calibration_store.py — stub `fetchrow` /
`execute` and assert the Python-side mapping: the UniqueViolation →
DuplicateEmailError translation, row → dataclass shaping, and the revoke
return semantics. The SQL text itself is validated by the proxy's sqlx
migration set at boot, not here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import asyncpg
import pytest

from cascadia_dashboard.auth.store import AsyncpgAuthStore, DuplicateEmailError


def _pool() -> MagicMock:
    return MagicMock()


@pytest.mark.asyncio
async def test_create_user_ok() -> None:
    pool = _pool()
    pool.execute = AsyncMock(return_value="INSERT 0 1")
    store = AsyncpgAuthStore(pool)
    # Should not raise.
    await store.create_user(
        user_id="u1", email="a@b.dev", password_hash="$argon2id$...", display_name="A"
    )
    pool.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_user_duplicate_maps_to_domain_error() -> None:
    pool = _pool()
    pool.execute = AsyncMock(side_effect=asyncpg.exceptions.UniqueViolationError("dup"))
    store = AsyncpgAuthStore(pool)
    with pytest.raises(DuplicateEmailError):
        await store.create_user(
            user_id="u1", email="a@b.dev", password_hash="h", display_name=None
        )


@pytest.mark.asyncio
async def test_get_user_by_email_maps_row() -> None:
    pool = _pool()
    pool.fetchrow = AsyncMock(
        return_value={
            "user_id": "u1",
            "email": "a@b.dev",
            "password_hash": "$argon2id$h",
            "display_name": "A",
            "role": "admin",
        }
    )
    store = AsyncpgAuthStore(pool)
    u = await store.get_user_by_email("A@B.dev")
    assert u is not None
    assert u.user_id == "u1"
    assert u.email == "a@b.dev"
    assert u.password_hash == "$argon2id$h"
    assert u.role == "admin"


@pytest.mark.asyncio
async def test_get_user_by_email_missing_returns_none() -> None:
    pool = _pool()
    pool.fetchrow = AsyncMock(return_value=None)
    store = AsyncpgAuthStore(pool)
    assert await store.get_user_by_email("ghost@b.dev") is None


@pytest.mark.asyncio
async def test_get_active_session_maps_row() -> None:
    pool = _pool()
    exp = datetime.now(timezone.utc)
    pool.fetchrow = AsyncMock(
        return_value={
            "user_id": "u1",
            "expires_at": exp,
            "email": "a@b.dev",
            "display_name": None,
            "role": "operator",
        }
    )
    store = AsyncpgAuthStore(pool)
    s = await store.get_active_session("deadbeef")
    assert s is not None
    assert s.user_id == "u1"
    assert s.email == "a@b.dev"
    assert s.role == "operator"
    assert s.expires_at == exp


@pytest.mark.asyncio
async def test_get_active_session_none_when_no_live_row() -> None:
    # The liveness filter (revoked/expired) lives in SQL; a dead session just
    # returns no row, which must map to None.
    pool = _pool()
    pool.fetchrow = AsyncMock(return_value=None)
    store = AsyncpgAuthStore(pool)
    assert await store.get_active_session("deadbeef") is None


@pytest.mark.asyncio
async def test_revoke_session_returns_true_when_row_flipped() -> None:
    pool = _pool()
    pool.fetchrow = AsyncMock(return_value={"session_id": "s1"})
    store = AsyncpgAuthStore(pool)
    assert await store.revoke_session("deadbeef") is True


@pytest.mark.asyncio
async def test_revoke_session_returns_false_when_already_dead() -> None:
    pool = _pool()
    pool.fetchrow = AsyncMock(return_value=None)
    store = AsyncpgAuthStore(pool)
    assert await store.revoke_session("deadbeef") is False
