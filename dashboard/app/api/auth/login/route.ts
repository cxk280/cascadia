// Login: forward {email, password} to the dashboard-api and, on success, set
// the httpOnly session cookie. The opaque token is consumed here and never
// reaches browser JS — the response body carries only the user object.

import { NextRequest } from "next/server";

import { forwardCredentialPost } from "@/lib/auth";

export async function POST(req: NextRequest) {
  return forwardCredentialPost(req, "/api/auth/login", 200);
}
