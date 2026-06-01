"""Sending the account-confirmation email.

Pluggable `EmailSender`:
  - `SmtpEmailSender` — real delivery via SMTP (works with SES / Postmark /
    Resend / Gmail / any SMTP host). Configured from `CASCADIA_SMTP_*`.
  - `LogEmailSender` — dev fallback when no SMTP is configured: logs the
    verification link so the flow works end-to-end offline (copy it from the
    dashboard-api log).

`smtplib` is blocking, so the send runs in a worker thread to keep the asyncio
event loop responsive.
"""

from __future__ import annotations

import asyncio
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Protocol, runtime_checkable

log = logging.getLogger(__name__)

_SUBJECT = "Confirm your Cascadia account"


def _body(verify_url: str) -> str:
    return (
        "Welcome to Cascadia.\n\n"
        "Confirm your operator account by opening this link:\n\n"
        f"  {verify_url}\n\n"
        "The link expires in 24 hours. If you didn't create this account, "
        "you can ignore this email.\n"
    )


@runtime_checkable
class EmailSender(Protocol):
    async def send_verification(self, *, to_email: str, verify_url: str) -> None: ...


class LogEmailSender:
    """Dev fallback: log the verification link instead of sending. The signup
    flow still works end-to-end — grab the link from the log."""

    async def send_verification(self, *, to_email: str, verify_url: str) -> None:
        log.warning(
            "[email:dev] SMTP not configured; verification link for %s -> %s",
            to_email,
            verify_url,
        )


class SmtpEmailSender:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        user: str | None,
        password: str | None,
        from_addr: str,
        use_ssl: bool,
        starttls: bool,
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._from = from_addr
        self._use_ssl = use_ssl
        self._starttls = starttls

    async def send_verification(self, *, to_email: str, verify_url: str) -> None:
        msg = EmailMessage()
        msg["From"] = self._from
        msg["To"] = to_email
        msg["Subject"] = _SUBJECT
        msg.set_content(_body(verify_url))
        # smtplib is blocking — keep it off the event loop.
        await asyncio.to_thread(self._send_sync, msg)

    def _send_sync(self, msg: EmailMessage) -> None:
        ctx = ssl.create_default_context()
        if self._use_ssl:
            with smtplib.SMTP_SSL(self._host, self._port, context=ctx) as s:
                if self._user:
                    s.login(self._user, self._password or "")
                s.send_message(msg)
        else:
            with smtplib.SMTP(self._host, self._port) as s:
                if self._starttls:
                    s.starttls(context=ctx)
                if self._user:
                    s.login(self._user, self._password or "")
                s.send_message(msg)


def email_sender_from_env() -> EmailSender:
    """Build an `EmailSender` from the environment. With no `CASCADIA_SMTP_HOST`
    set, returns the dev log-only sender (the flow works; nothing is actually
    sent)."""
    host = os.environ.get("CASCADIA_SMTP_HOST")
    if not host:
        return LogEmailSender()
    port = int(os.environ.get("CASCADIA_SMTP_PORT", "587"))
    explicit_ssl = os.environ.get("CASCADIA_SMTP_SSL", "").lower() in ("1", "true")
    use_ssl = explicit_ssl or port == 465
    starttls = os.environ.get("CASCADIA_SMTP_STARTTLS", "true").lower() in ("1", "true")
    return SmtpEmailSender(
        host=host,
        port=port,
        user=os.environ.get("CASCADIA_SMTP_USER"),
        password=os.environ.get("CASCADIA_SMTP_PASS"),
        from_addr=os.environ.get("CASCADIA_SMTP_FROM", "no-reply@cascadia.local"),
        use_ssl=use_ssl,
        starttls=starttls and not use_ssl,
    )
