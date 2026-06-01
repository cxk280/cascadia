// Session probe for client components (e.g. the header user menu). Reads the
// httpOnly cookie server-side, validates it against the dashboard-api, and
// returns the user — or 401 with a null user. The token itself is never
// returned to the browser.

import { NextRequest, NextResponse } from "next/server";

import { SESSION_COOKIE, validateToken } from "@/lib/auth";

export async function GET(req: NextRequest) {
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  const user = await validateToken(token);
  if (!user) {
    return NextResponse.json({ user: null }, { status: 401 });
  }
  return NextResponse.json({ user });
}
