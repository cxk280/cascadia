// Signup: forward {email, password, display_name?} to the dashboard-api. This
// does NOT log the user in — signup is double-opt-in. The dashboard-api creates
// an unverified account and emails a confirmation link; the response carries no
// token, so no cookie is set. The user completes signup via /verify.

import { NextRequest } from "next/server";

import { forwardJson } from "@/lib/auth";

export async function POST(req: NextRequest) {
  return forwardJson(req, "/api/auth/signup");
}
