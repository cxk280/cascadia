// Browser-facing route handler that forwards to the dashboard-api's
// /api/proxy-reachable endpoint. Keeps the Python service off the public
// network: only the Next.js origin is exposed. Used by the
// ProxyReachabilityBanner client component which polls every 5s.

import { NextResponse } from "next/server";

import { SERVER_API_BASE } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET() {
  let res: Response;
  try {
    res = await fetch(`${SERVER_API_BASE}/api/proxy-reachable`, {
      cache: "no-store",
      // Bound the hop so a wedged dashboard-api doesn't leave this poll
      // pending forever (the banner polls it every few seconds).
      signal: AbortSignal.timeout(4_000),
    });
  } catch {
    // Don't leak the internal hostname / raw cause; report a clean 502 the
    // banner can render as "unreachable".
    return NextResponse.json({ reachable: false, detail: "dashboard-api unreachable" }, {
      status: 502,
      headers: { "Cache-Control": "no-store" },
    });
  }
  const body = await res.text();
  return new NextResponse(body, {
    status: res.status,
    headers: {
      "Content-Type": res.headers.get("content-type") ?? "application/json",
      "Cache-Control": "no-store",
    },
  });
}
