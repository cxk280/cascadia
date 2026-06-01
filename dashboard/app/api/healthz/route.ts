// Unauthenticated liveness endpoint for platform health checks (Railway).
//
// The operator dashboard's root `/` is now behind the auth gate, so a health
// check pointed at `/` would get a 302 → /login and read as unhealthy. This
// endpoint stays public (carved out in middleware) and returns a plain 200 so
// the platform can confirm the Next.js server is up without authenticating.

import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

export function GET() {
  return NextResponse.json({ status: "ok", service: "cascadia-dashboard" });
}
