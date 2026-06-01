// Logout: best-effort revoke the server-side session, then clear the cookie.
// Clearing the cookie is unconditional so the browser ends up logged out even
// if the revoke call fails (the session still expires server-side on its TTL).

import { NextRequest, NextResponse } from "next/server";

import { SERVER_API_BASE } from "@/lib/api";
import { SESSION_COOKIE, sessionCookieOptions } from "@/lib/auth";

const UPSTREAM_TIMEOUT_MS = 5_000;

export async function POST(req: NextRequest) {
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  if (token) {
    try {
      await fetch(`${SERVER_API_BASE}/api/auth/logout`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ token }),
        cache: "no-store",
        signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
      });
    } catch {
      // Swallow — we still clear the cookie below. The session will lapse on
      // its server-side TTL even if this revoke didn't land.
    }
  }
  const res = NextResponse.json({ ok: true });
  res.cookies.set(SESSION_COOKIE, "", sessionCookieOptions(0));
  return res;
}
