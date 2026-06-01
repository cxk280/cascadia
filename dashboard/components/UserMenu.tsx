"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

interface SessionUser {
  user_id: string;
  email: string;
  display_name: string | null;
}

// Header account control. Fetches the current session client-side (the token
// lives in an httpOnly cookie, so JS can't read it directly — it asks the
// server who it is via /api/auth/session) and offers sign-out. Rendered inside
// the Shell, which only appears on gated pages, so a session is expected.
export function UserMenu() {
  const router = useRouter();
  const [user, setUser] = useState<SessionUser | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let alive = true;
    fetch("/api/auth/session", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : { user: null }))
      .then((d) => {
        if (alive) setUser(d.user ?? null);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  // Close the dropdown on outside click.
  useEffect(() => {
    if (!open) return;
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  async function handleSignOut() {
    setBusy(true);
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } catch {
      // Ignore — the cookie clears regardless and we still redirect.
    }
    router.push("/login");
    router.refresh();
  }

  const label = user?.display_name?.trim() || user?.email || "Account";
  const initial = label.charAt(0).toUpperCase();

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className="flex items-center gap-2 rounded px-2 py-1 hover:bg-bg-raised text-sm"
      >
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-accent/15 text-accent text-xs font-semibold">
          {initial}
        </span>
        <span className="hidden sm:inline max-w-[14rem] truncate text-fg-muted">
          {label}
        </span>
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 mt-2 w-56 rounded-md border border-border bg-bg-surface shadow-xl shadow-black/30 py-1 z-50"
        >
          <div className="px-3 py-2 border-b border-border">
            <div className="text-xs text-fg-subtle uppercase tracking-widest">
              Signed in as
            </div>
            <div className="text-sm text-fg truncate">{user?.email ?? "…"}</div>
          </div>
          <button
            type="button"
            role="menuitem"
            onClick={handleSignOut}
            disabled={busy}
            className="w-full text-left px-3 py-2 text-sm text-fg-muted hover:text-fg hover:bg-bg-raised disabled:opacity-40"
          >
            {busy ? "Signing out…" : "Sign out"}
          </button>
        </div>
      )}
    </div>
  );
}
