// Catch-all proxy for /api/calibrate/* — forwards GET and POST verbatim
// to the FastAPI dashboard-api. Keeps the Python service off the public
// network: only the Next.js origin is exposed.

import { NextRequest, NextResponse } from "next/server";

import { SERVER_API_BASE } from "@/lib/api";

const UPSTREAM_TIMEOUT_MS = 8_000;

async function proxy(req: NextRequest, ctx: { params: { path: string[] } }) {
  const segments = ctx.params.path;
  // Defense-in-depth against path traversal: reject any segment that could
  // escape the `/api/calibrate/` prefix once the URL is normalized — `.`,
  // `..`, empty, or a segment containing a (possibly percent-decoded) slash
  // or backslash. Next normalizes most of these out of dynamic segments, but
  // we don't rely on that. Without this, e.g. `..%2foverview` resolves to
  // `/api/overview`, reaching sibling routes outside the calibrate prefix.
  for (const seg of segments) {
    if (seg === "" || seg === "." || seg === ".." || /[/\\]/.test(seg)) {
      return NextResponse.json({ detail: "invalid path" }, { status: 400 });
    }
  }
  const subpath = segments.join("/");
  const search = req.nextUrl.search;
  const upstream = `${SERVER_API_BASE}/api/calibrate/${subpath}${search}`;

  const init: RequestInit = {
    method: req.method,
    headers: { Accept: "application/json" },
    // For POST/PUT, forward the body and content-type.
    ...(req.method !== "GET"
      ? {
          headers: {
            Accept: "application/json",
            "Content-Type": req.headers.get("content-type") ?? "application/json",
          },
          body: await req.text(),
        }
      : {}),
    cache: "no-store",
    // Bound the Next→FastAPI hop so a wedged dashboard-api doesn't hang the
    // browser request (and the label/rubric spinner) indefinitely.
    signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS),
  };

  let res: Response;
  try {
    res = await fetch(upstream, init);
  } catch (err) {
    // Upstream down / DNS failure / timeout. Return a clean 502 without
    // echoing the internal hostname or raw fetch `cause` to the client.
    const reason =
      err instanceof Error && err.name === "TimeoutError"
        ? "calibration service timed out"
        : "calibration service unreachable";
    return NextResponse.json({ detail: reason }, { status: 502 });
  }
  const body = await res.text();
  return new NextResponse(body, {
    status: res.status,
    headers: {
      "Content-Type": res.headers.get("content-type") ?? "application/json",
    },
  });
}

export async function GET(req: NextRequest, ctx: { params: { path: string[] } }) {
  return proxy(req, ctx);
}

export async function POST(req: NextRequest, ctx: { params: { path: string[] } }) {
  return proxy(req, ctx);
}
