// Server-side auth helpers for the operator dashboard.
//
// Session model: the browser holds an opaque token in an httpOnly cookie
// (`cascadia_session`). It is NEVER exposed to browser JS. Validation is
// delegated to the dashboard-api (`POST /api/auth/session`), which checks the
// token against Postgres (unrevoked + unexpired) — so logout/expiry take
// effect immediately and nothing is trusted client-side. See PLAN.md §9
// (2026-06-01) for why this is opaque-server-sessions rather than JWT.
//
// NOTE: this module imports `next/headers` and is therefore server-only. Do
// NOT import it from `middleware.ts` (Edge runtime) — the middleware inlines
// its own token check.

import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";

import { SERVER_API_BASE } from "@/lib/api";

export const SESSION_COOKIE = "cascadia_session";

// 30 days — mirrors the dashboard-api `SESSION_TTL`. The cookie's lifetime is
// advisory; the authoritative expiry lives on the server-side session row.
export const SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30;

const VALIDATE_TIMEOUT_MS = 4_000;

export interface SessionUser {
  user_id: string;
  email: string;
  display_name: string | null;
}

export function sessionCookieOptions(maxAge: number) {
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    // Only mark Secure in production — local dev is plain http, where a
    // Secure cookie would silently never be stored and login would "fail".
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge,
  };
}

// Validate an opaque token against the dashboard-api. Returns the owning user
// or null (absent / expired / revoked / service unreachable). Pure fetch — no
// `next/headers` — so it's safe to call from route handlers.
export async function validateToken(
  token: string | undefined | null,
): Promise<SessionUser | null> {
  if (!token) return null;
  try {
    const res = await fetch(`${SERVER_API_BASE}/api/auth/session`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ token }),
      cache: "no-store",
      signal: AbortSignal.timeout(VALIDATE_TIMEOUT_MS),
    });
    if (!res.ok) return null;
    const data = (await res.json()) as { user?: SessionUser };
    return data.user ?? null;
  } catch {
    // Fail closed: an unreachable auth service means "not authenticated",
    // never "allowed through".
    return null;
  }
}

// Read + validate the session cookie from within a server component.
export async function getSession(): Promise<SessionUser | null> {
  const token = cookies().get(SESSION_COOKIE)?.value;
  return validateToken(token);
}

const UPSTREAM_TIMEOUT_MS = 8_000;

// Shared body for the /login and /signup route handlers: forward the
// credential POST to the dashboard-api, and on success mint the httpOnly
// session cookie while stripping the raw token from the browser-facing body.
export async function forwardCredentialPost(
  req: NextRequest,
  upstreamPath: string,
  successStatus = 200,
): Promise<NextResponse> {
  let body: string;
  try {
    body = await req.text();
  } catch {
    return NextResponse.json({ detail: "invalid request body" }, { status: 400 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${SERVER_API_BASE}${upstreamPath}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        // Pass the real client UA through so the session row records it
        // rather than the Node fetch default.
        "User-Agent": req.headers.get("user-agent") ?? "cascadia-dashboard",
      },
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
    });
  } catch {
    return NextResponse.json(
      { detail: "authentication service unreachable" },
      { status: 502 },
    );
  }

  const data = (await upstream.json().catch(() => ({}))) as {
    detail?: string;
    token?: string;
    user?: unknown;
  };
  if (!upstream.ok) {
    return NextResponse.json(
      { detail: data.detail ?? "request failed" },
      { status: upstream.status },
    );
  }
  if (!data.token) {
    return NextResponse.json(
      { detail: "authentication service returned an unexpected response" },
      { status: 502 },
    );
  }
  const res = NextResponse.json({ user: data.user }, { status: successStatus });
  res.cookies.set(SESSION_COOKIE, data.token, sessionCookieOptions(SESSION_MAX_AGE_SECONDS));
  return res;
}
