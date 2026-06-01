"""Password hashing and opaque session-token primitives.

Isolated from the store and routes so the crypto choices live in one place:
  - Passwords: Argon2id (argon2-cffi defaults — a memory-hard KDF).
  - Session tokens: 256 bits of CSPRNG entropy, URL-safe. We hand the raw
    token to the client (httpOnly cookie) and persist only its SHA-256, so a
    DB leak can't be replayed.
"""

from __future__ import annotations

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

# One shared hasher. argon2-cffi's defaults (currently t=3, m=64MiB, p=4) are
# a sensible 2020s baseline; bumping them later is safe because the chosen
# params are encoded in each stored PHC string and `needs_rehash` flags old
# rows for transparent upgrade on next login.
_hasher = PasswordHasher()

# 32 bytes → 256 bits of entropy. token_urlsafe yields ~43 chars; well under
# the 512-char cap the wire type enforces and the cookie can hold.
_TOKEN_BYTES = 32


def hash_password(password: str) -> str:
    """Return an Argon2id PHC string for `password`."""
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    """Constant-time-ish verify via argon2. Returns False on mismatch or a
    malformed stored hash rather than raising, so callers branch on a bool."""
    try:
        return _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    """True if `stored_hash` was made with weaker params than the current
    policy and should be re-hashed after a successful verify."""
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return False


def generate_session_token() -> str:
    """A fresh opaque session token. This is the secret the client holds."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(token: str) -> str:
    """SHA-256 hex of a session token — the only form we persist.

    SHA-256 (not Argon2) is correct here: the token already has full 256-bit
    entropy, so there's nothing to brute-force; we just need a fast,
    deterministic fingerprint to index on.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
