"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

type Mode = "login" | "signup";

// Only allow redirecting back to an internal, single-slash path. Blocks
// open-redirect payloads like `//evil.com` or `https://evil.com` smuggled in
// via ?next=.
function safeNext(raw: string | null): string {
  if (!raw) return "/";
  if (!raw.startsWith("/") || raw.startsWith("//")) return "/";
  return raw;
}

// FastAPI 422s come back as an array of {msg,...}; everything else is a
// string. Normalize to something showable without leaking pydantic internals.
function formatError(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string };
    if (first?.msg) return first.msg.replace(/^Value error,\s*/, "");
  }
  return "Something went wrong. Please check your details and try again.";
}

const PASSWORD_MIN = 8;

// Best-effort resend; always shows the same neutral confirmation (the server
// won't reveal whether the account exists).
async function resendVerification(email: string): Promise<void> {
  await fetch("/api/auth/resend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: email.trim() }),
  }).catch(() => {});
}

export function AuthForm({ mode }: { mode: Mode }) {
  const router = useRouter();
  const next = safeNext(useSearchParams().get("next"));

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Set after a successful signup → render the "check your email" panel.
  const [sentTo, setSentTo] = useState<string | null>(null);
  // Set when login is refused because the email isn't verified → offer resend.
  const [needsVerify, setNeedsVerify] = useState(false);
  const [resendMsg, setResendMsg] = useState<string | null>(null);

  const isSignup = mode === "signup";

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setNeedsVerify(false);
    setResendMsg(null);

    if (isSignup) {
      if (password.length < PASSWORD_MIN) {
        setError(`Password must be at least ${PASSWORD_MIN} characters.`);
        return;
      }
      if (password !== confirm) {
        setError("Passwords don't match.");
        return;
      }
    }

    setBusy(true);
    try {
      const endpoint = isSignup ? "/api/auth/signup" : "/api/auth/login";
      const body: Record<string, string> = { email: email.trim(), password };
      if (isSignup && displayName.trim()) body.display_name = displayName.trim();

      const res = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      if (isSignup) {
        if (res.ok) {
          // No session yet — signup is double opt-in. Show the check-email panel.
          setSentTo(email.trim());
          setBusy(false);
          return;
        }
        const data = await res.json().catch(() => ({}));
        setError(formatError((data as { detail?: unknown }).detail));
        setBusy(false);
        return;
      }

      // login
      if (res.ok) {
        router.push(next);
        router.refresh();
        return;
      }
      const data = await res.json().catch(() => ({}));
      if (res.status === 403) {
        // Account exists but email isn't verified.
        setError("Your email isn't verified yet — check your inbox for the confirmation link.");
        setNeedsVerify(true);
      } else {
        setError(formatError((data as { detail?: unknown }).detail));
      }
      setBusy(false);
    } catch {
      setError("Couldn't reach the server. Please try again.");
      setBusy(false);
    }
  }

  // Post-signup: confirmation-sent panel.
  if (sentTo) {
    return (
      <div className="space-y-4">
        <div className="border border-accent/30 bg-accent/5 text-sm rounded-md px-3 py-3">
          <div className="font-medium text-fg">Check your email</div>
          <p className="text-fg-muted mt-1">
            We sent a confirmation link to <span className="text-fg">{sentTo}</span>.
            Click it to finish creating your account — it expires in 24 hours.
          </p>
        </div>
        <button
          type="button"
          onClick={async () => {
            await resendVerification(sentTo);
            setResendMsg("If that account still needs confirming, we've re-sent the link.");
          }}
          className="w-full border border-border rounded px-4 py-2 text-sm text-fg-muted hover:text-fg hover:bg-bg-raised"
        >
          Resend confirmation email
        </button>
        {resendMsg && <div className="text-xs text-fg-muted text-center">{resendMsg}</div>}
        <div className="text-xs text-fg-muted text-center pt-2">
          <Link href="/login" className="text-accent hover:underline">
            Back to sign in
          </Link>
        </div>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4" noValidate>
      <label className="block">
        <span className="text-xs text-fg-muted">Email</span>
        <input
          type="email"
          name="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => {
            setEmail(e.target.value);
            if (error) setError(null);
          }}
          placeholder="you@company.com"
          autoFocus
          className="mt-1 w-full bg-bg-raised border border-border rounded px-3 py-2 text-sm focus:outline-none focus:border-accent"
        />
      </label>

      {isSignup && (
        <label className="block">
          <span className="text-xs text-fg-muted">
            Display name <span className="text-fg-subtle">(optional)</span>
          </span>
          <input
            type="text"
            name="display_name"
            autoComplete="name"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="Chris King"
            className="mt-1 w-full bg-bg-raised border border-border rounded px-3 py-2 text-sm focus:outline-none focus:border-accent"
          />
        </label>
      )}

      <label className="block">
        <span className="text-xs text-fg-muted">Password</span>
        <input
          type="password"
          name="password"
          autoComplete={isSignup ? "new-password" : "current-password"}
          required
          minLength={isSignup ? PASSWORD_MIN : undefined}
          value={password}
          onChange={(e) => {
            setPassword(e.target.value);
            if (error) setError(null);
          }}
          placeholder={isSignup ? `At least ${PASSWORD_MIN} characters` : "••••••••"}
          className="mt-1 w-full bg-bg-raised border border-border rounded px-3 py-2 text-sm focus:outline-none focus:border-accent"
        />
      </label>

      {isSignup && (
        <label className="block">
          <span className="text-xs text-fg-muted">Confirm password</span>
          <input
            type="password"
            name="confirm_password"
            autoComplete="new-password"
            required
            value={confirm}
            onChange={(e) => {
              setConfirm(e.target.value);
              if (error) setError(null);
            }}
            placeholder="••••••••"
            className="mt-1 w-full bg-bg-raised border border-border rounded px-3 py-2 text-sm focus:outline-none focus:border-accent"
          />
        </label>
      )}

      {error && (
        <div
          role="alert"
          className="border border-accent-danger/40 bg-accent-danger/5 text-accent-danger text-sm rounded-md px-3 py-2"
        >
          {error}
          {needsVerify && (
            <button
              type="button"
              onClick={async () => {
                await resendVerification(email);
                setResendMsg("If that account still needs confirming, we've re-sent the link.");
              }}
              className="mt-2 block underline hover:no-underline"
            >
              Resend confirmation email
            </button>
          )}
        </div>
      )}
      {resendMsg && <div className="text-xs text-fg-muted">{resendMsg}</div>}

      <button
        type="submit"
        disabled={busy}
        className="w-full bg-accent text-bg font-medium px-4 py-2 rounded text-sm disabled:opacity-40"
      >
        {busy ? "…" : isSignup ? "Create account" : "Sign in"}
      </button>

      <div className="text-xs text-fg-muted text-center pt-2">
        {isSignup ? (
          <>
            Already have an account?{" "}
            <Link href="/login" className="text-accent hover:underline">
              Sign in
            </Link>
          </>
        ) : (
          <>
            New to Cascadia?{" "}
            <Link href="/signup" className="text-accent hover:underline">
              Create an account
            </Link>
          </>
        )}
      </div>
    </form>
  );
}
