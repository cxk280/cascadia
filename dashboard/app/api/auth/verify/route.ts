// Verify: forward the one-time token from the emailed link to the dashboard-api.
// On success the account is confirmed and a session is issued — so this sets
// the httpOnly cookie (logging the user in) exactly like /login.

import { NextRequest } from "next/server";

import { forwardCredentialPost } from "@/lib/auth";

export async function POST(req: NextRequest) {
  return forwardCredentialPost(req, "/api/auth/verify", 200);
}
