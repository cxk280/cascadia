// Signup: forward {email, password, display_name?} to the dashboard-api and,
// on success (201), set the httpOnly session cookie so the new account is
// logged in immediately. Same token-stripping discipline as /login.

import { NextRequest } from "next/server";

import { forwardCredentialPost } from "@/lib/auth";

export async function POST(req: NextRequest) {
  return forwardCredentialPost(req, "/api/auth/signup", 201);
}
