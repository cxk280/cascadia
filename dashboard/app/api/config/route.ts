// Browser-facing route handler that forwards to the dashboard-api's
// /api/config endpoint. Mirrors the proxy-reachable pattern. Lets a future
// client-side component poll the data-residency posture without exposing
// the Python service publicly.

import { NextResponse } from "next/server";

import { SERVER_API_BASE } from "@/lib/api";

export const dynamic = "force-dynamic";

export async function GET() {
  let res: Response;
  try {
    res = await fetch(`${SERVER_API_BASE}/api/config`, {
      cache: "no-store",
      signal: AbortSignal.timeout(4_000),
    });
  } catch {
    // Don't leak the internal hostname / raw cause to the client.
    return NextResponse.json({ detail: "dashboard-api unreachable" }, {
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
