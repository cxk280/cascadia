// Resend the confirmation email. Forwards {email} to the dashboard-api, which
// returns a generic ack regardless of whether the account exists (no
// enumeration). No session involved.

import { NextRequest } from "next/server";

import { forwardJson } from "@/lib/auth";

export async function POST(req: NextRequest) {
  return forwardJson(req, "/api/auth/resend-verification");
}
