#!/usr/bin/env bash
# Send ONE test confirmation email through the configured SMTP, to verify
# delivery before relying on it in the signup flow. Reads the same
# CASCADIA_SMTP_* env vars the dashboard-api uses; with none set it falls back
# to the dev "log the link" sender (and says so), so this also confirms which
# sender is active.
#
#   export CASCADIA_SMTP_HOST=smtp.resend.com CASCADIA_SMTP_PORT=465 \
#          CASCADIA_SMTP_USER=resend CASCADIA_SMTP_PASS=re_... \
#          CASCADIA_SMTP_FROM=onboarding@resend.dev
#   ./scripts/test-email.sh you@example.com
#
# The password is read from the environment - never pass it on the command line.

set -euo pipefail

TO="${1:-}"
if [ -z "$TO" ]; then
  echo "usage: CASCADIA_SMTP_*=... ./scripts/test-email.sh <recipient-email>" >&2
  exit 2
fi

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO/services/dashboard-api"
PY=".venv/bin/python"
[ -x "$PY" ] || PY="python3"

"$PY" - "$TO" <<'PYEOF'
import asyncio
import os
import sys

from cascadia_dashboard.auth.email import email_sender_from_env

to = sys.argv[1]
sender = email_sender_from_env()
print(f"[test-email] active sender: {type(sender).__name__}")
if type(sender).__name__ == "LogEmailSender":
    print("[test-email] NOTE: CASCADIA_SMTP_HOST is unset, so nothing is actually")
    print("[test-email]       sent - the link is only logged. Set CASCADIA_SMTP_* to")
    print("[test-email]       send for real.")
else:
    print(f"[test-email] host={os.environ.get('CASCADIA_SMTP_HOST')} "
          f"port={os.environ.get('CASCADIA_SMTP_PORT', '587')} "
          f"from={os.environ.get('CASCADIA_SMTP_FROM', 'no-reply@cascadia.local')}")

url = "https://example.com/verify?token=connectivity-check-not-a-real-token"
try:
    asyncio.run(sender.send_verification(to_email=to, verify_url=url))
except Exception as exc:  # surface SMTP errors clearly
    print(f"[test-email] FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
    sys.exit(1)
print(f"[test-email] OK - handed off to the sender for {to} (check inbox + spam).")
PYEOF
