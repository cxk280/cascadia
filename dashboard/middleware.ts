// Session gate for the Cascadia operator dashboard.
//
// Replaces the previous HTTP Basic Auth popup (PLAN.md §9, 2026-06-01). The
// dashboard now has first-class email/password accounts; this middleware is
// the front door.
//
// Authoritative validation: we don't trust mere cookie *presence*. For every
// gated request we POST the opaque token to the dashboard-api, which checks it
// against Postgres (unrevoked + unexpired). That makes logout and expiry take
// effect on the very next request, and a forged/garbage cookie never gets in.
// (This is the dashboard, not the proxy hot path — blocking on the API here is
// fine; the §9 "proxy must not block on Postgres" invariant is about the Rust
// gateway, not this service.)
//
// Public (no session required):
//   - /login, /signup                      (the auth pages themselves)
//   - /api/auth/*                           (login/signup/logout/session)
//   - /api/healthz                          (platform liveness check)
//   - /calibrate/rubric, /api/calibrate/rubric   (public methodology, §9)
//   - /api/config, /api/proxy-reachable     (non-secret proxy config, §9;
//                                            the live-pip banner polls these)
//
// Everything else under the operator dashboard is gated.
//
// Local-dev escape hatch: set CASCADIA_AUTH_DISABLED=true to bypass the gate
// when running the UI without the Python backend. Honored ONLY outside
// production — prod always enforces.

import { NextRequest, NextResponse } from "next/server";

const SESSION_COOKIE = "cascadia_session";
const API_BASE =
  process.env.CASCADIA_DASHBOARD_API_BASE ?? "http://127.0.0.1:18082";
const VALIDATE_TIMEOUT_MS = 4_000;

function isPublicPath(pathname: string): boolean {
  if (pathname === "/login" || pathname === "/signup") return true;
  if (pathname === "/api/auth" || pathname.startsWith("/api/auth/")) return true;
  if (pathname === "/api/healthz") return true;
  if (pathname === "/calibrate/rubric" || pathname === "/api/calibrate/rubric") {
    return true;
  }
  if (pathname === "/api/config" || pathname === "/api/proxy-reachable") {
    return true;
  }
  return false;
}

async function tokenIsValid(token: string): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/api/auth/session`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
      cache: "no-store",
      signal: AbortSignal.timeout(VALIDATE_TIMEOUT_MS),
    });
    return res.ok;
  } catch {
    // Fail closed — an unreachable auth service denies access, it never
    // opens the gate.
    return false;
  }
}

function authDisabledInDev(): boolean {
  return (
    process.env.NODE_ENV !== "production" &&
    process.env.CASCADIA_AUTH_DISABLED === "true"
  );
}

export async function middleware(req: NextRequest): Promise<NextResponse> {
  const { pathname } = req.nextUrl;

  if (isPublicPath(pathname) || authDisabledInDev()) {
    return NextResponse.next();
  }

  const token = req.cookies.get(SESSION_COOKIE)?.value;
  const ok = token ? await tokenIsValid(token) : false;
  if (ok) {
    return NextResponse.next();
  }

  // API routes get a clean 401 (a redirect would be nonsense to a fetch()).
  if (pathname.startsWith("/api/")) {
    return NextResponse.json(
      { detail: "authentication required" },
      { status: 401, headers: { "Cache-Control": "no-store" } },
    );
  }

  // Page routes redirect to /login, preserving the intended destination.
  const loginUrl = req.nextUrl.clone();
  loginUrl.pathname = "/login";
  loginUrl.search = "";
  loginUrl.searchParams.set("next", pathname + req.nextUrl.search);
  const res = NextResponse.redirect(loginUrl);
  // Drop a stale/invalid cookie so we don't bounce on it next time.
  if (token) {
    res.cookies.set(SESSION_COOKIE, "", { path: "/", maxAge: 0 });
  }
  return res;
}

// Run on everything except Next internals and static assets (paths with a
// file extension). The public carve-outs above are enforced inside
// `middleware()` since the matcher can't express "all of /api/calibrate
// except /rubric".
export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|.*\\.).*)"],
};
