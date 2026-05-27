// Basic-auth gate for the calibration labeling app.
//
// Public (no auth):
//   - /calibrate/rubric              (rubric page, methodology contract)
//   - GET /api/calibrate/rubric      (same content, JSON)
//   - everything outside /calibrate* and /api/calibrate/*
//
// Gated (HTTP Basic Auth):
//   - /calibrate                     (onboarding)
//   - /calibrate/label               (labeling UI)
//   - GET  /api/calibrate/next
//   - POST /api/calibrate/reviewers
//   - POST /api/calibrate/labels
//   - GET  /api/calibrate/progress
//
// Credentials come from env:
//   - CASCADIA_CALIBRATE_USER  (defaults to "cascadia" outside production;
//                               in production we log a warning if unset)
//   - CASCADIA_CALIBRATE_PASS  (required in production — hard fail at first
//                               request if unset)
//
// The dashboard-api (FastAPI) is intentionally NOT gated here — it sits on
// Railway's internal service-to-service network and is reached only by the
// Next.js proxy at /api/calibrate/[...path]. CORS in the FastAPI app keeps
// strangers from cross-origin POSTing if it ever gets a public URL.

import { NextRequest, NextResponse } from "next/server";

const REALM = 'Basic realm="Cascadia Calibration", charset="UTF-8"';

function unauthorized(): NextResponse {
  return new NextResponse("Authentication required.", {
    status: 401,
    headers: {
      "WWW-Authenticate": REALM,
      "Content-Type": "text/plain; charset=utf-8",
      // Don't let intermediaries cache 401s.
      "Cache-Control": "no-store",
    },
  });
}

function serverMisconfigured(detail: string): NextResponse {
  // We deliberately do not surface the detail to the client — that would
  // leak which env var is missing. Log it server-side instead.
  // eslint-disable-next-line no-console
  console.error(`[calibrate-auth] server misconfigured: ${detail}`);
  return new NextResponse("Service unavailable.", {
    status: 503,
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

// Constant-time string compare. Edge runtime doesn't have node:crypto's
// timingSafeEqual, so we hand-roll the standard XOR-accumulator pattern.
function timingSafeEqual(a: string, b: string): boolean {
  // Compare lengths via the accumulator so we don't early-return on
  // length mismatch (which would leak length).
  const aLen = a.length;
  const bLen = b.length;
  const len = Math.max(aLen, bLen);
  let diff = aLen ^ bLen;
  for (let i = 0; i < len; i++) {
    const ac = i < aLen ? a.charCodeAt(i) : 0;
    const bc = i < bLen ? b.charCodeAt(i) : 0;
    diff |= ac ^ bc;
  }
  return diff === 0;
}

function parseBasic(header: string | null): { user: string; pass: string } | null {
  if (!header) return null;
  const [scheme, encoded] = header.split(" ");
  if (!scheme || scheme.toLowerCase() !== "basic" || !encoded) return null;
  let decoded: string;
  try {
    decoded = atob(encoded);
  } catch {
    return null;
  }
  // Username can't contain ":", password can.
  const idx = decoded.indexOf(":");
  if (idx < 0) return null;
  return { user: decoded.slice(0, idx), pass: decoded.slice(idx + 1) };
}

function isProd(): boolean {
  return process.env.NODE_ENV === "production";
}

// Warn-once state for the missing-USER fallback.
let _warnedMissingUser = false;

function expectedCreds(): { user: string; pass: string } | null {
  const rawUser = process.env.CASCADIA_CALIBRATE_USER;
  const pass = process.env.CASCADIA_CALIBRATE_PASS;

  if (!pass) {
    if (isProd()) {
      // Hard fail in production — don't open the gate without a password.
      return null;
    }
    // Outside prod: no password means no gate is configured. Treat as
    // misconfigured so callers don't accidentally rely on a default in dev.
    return null;
  }

  let user: string;
  if (rawUser && rawUser.length > 0) {
    user = rawUser;
  } else {
    user = "cascadia";
    if (isProd() && !_warnedMissingUser) {
      _warnedMissingUser = true;
      // eslint-disable-next-line no-console
      console.warn(
        '[calibrate-auth] CASCADIA_CALIBRATE_USER unset in production; ' +
          'defaulting to "cascadia". Set it explicitly to silence this warning.'
      );
    }
  }
  return { user, pass };
}

// Decide whether a given pathname needs the gate. The matcher below already
// scopes us to /calibrate* and /api/calibrate/*, so here we only carve out
// the public rubric endpoints.
function isPublicCalibratePath(pathname: string): boolean {
  // Public rubric page.
  if (pathname === "/calibrate/rubric") return true;
  // Public rubric JSON endpoint (no trailing slash, no subpaths).
  if (pathname === "/api/calibrate/rubric") return true;
  return false;
}

export function middleware(req: NextRequest): NextResponse {
  const { pathname } = req.nextUrl;

  if (isPublicCalibratePath(pathname)) {
    return NextResponse.next();
  }

  const expected = expectedCreds();
  if (!expected) {
    if (isProd()) {
      return serverMisconfigured("CASCADIA_CALIBRATE_PASS unset in production");
    }
    // Dev with no password configured: gate is disabled. Pass through so
    // local development doesn't hit a dead end when the env var isn't set.
    return NextResponse.next();
  }

  const got = parseBasic(req.headers.get("authorization"));
  if (!got) {
    return unauthorized();
  }
  // Run both compares so we don't short-circuit on the user mismatch.
  const userOk = timingSafeEqual(got.user, expected.user);
  const passOk = timingSafeEqual(got.pass, expected.pass);
  if (!(userOk && passOk)) {
    return unauthorized();
  }

  return NextResponse.next();
}

// Scope: gate the calibrate UI and the four protected API endpoints. The
// /api/calibrate/rubric carve-out is enforced inside `middleware()` above
// (the matcher can't easily express "everything under /api/calibrate
// except /rubric").
export const config = {
  matcher: [
    "/calibrate",
    "/calibrate/:path*",
    "/api/calibrate/:path*",
  ],
};
