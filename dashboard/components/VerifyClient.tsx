"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";

type State = "verifying" | "ok" | "error";

// Consumes the one-time token from the emailed link. On success the route
// handler sets the session cookie, so we land in the dashboard logged in.
export function VerifyClient() {
  const router = useRouter();
  const token = useSearchParams().get("token");
  const [state, setState] = useState<State>("verifying");
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return; // tokens are single-use — never POST twice
    ran.current = true;
    if (!token) {
      setState("error");
      return;
    }
    fetch("/api/auth/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    })
      .then((res) => {
        if (res.ok) {
          setState("ok");
          router.push("/overview");
          router.refresh();
        } else {
          setState("error");
        }
      })
      .catch(() => setState("error"));
  }, [token, router]);

  if (state === "verifying") {
    return <p className="text-sm text-fg-muted">Confirming your account…</p>;
  }
  if (state === "ok") {
    return <p className="text-sm text-fg-muted">Confirmed — taking you to the dashboard…</p>;
  }
  return (
    <div className="space-y-3">
      <div
        role="alert"
        className="border border-accent-danger/40 bg-accent-danger/5 text-accent-danger text-sm rounded-md px-3 py-2"
      >
        This confirmation link is invalid, expired, or already used.
      </div>
      <p className="text-xs text-fg-muted">
        Try signing in — if your email still needs confirming, you can resend the
        link from there.
      </p>
      <Link href="/login" className="text-accent hover:underline text-sm">
        Back to sign in
      </Link>
    </div>
  );
}
