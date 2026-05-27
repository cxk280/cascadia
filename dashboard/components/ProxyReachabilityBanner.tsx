"use client";

import { useEffect, useRef, useState } from "react";

interface ReadyzPayload {
  status?: string;
  passed_checks?: string[];
  failed_checks?: string[];
  shutdown_remaining_secs?: number;
  shutdown_timeout_secs?: number;
}

interface State {
  reachable: boolean;
  probed: string;
  readyz?: ReadyzPayload;
}

type DisplayState = "unreachable" | "shutting_down" | "no_db" | "reconnected" | "healthy";

function classify(s: State): DisplayState {
  if (!s.reachable) return "unreachable";
  if (
    s.readyz?.status === "shutting_down" ||
    s.readyz?.failed_checks?.includes("shutting_down")
  )
    return "shutting_down";
  if (s.readyz?.passed_checks?.includes("postgres_not_configured")) return "no_db";
  return "healthy";
}

/// Single source of truth for proxy state on every dashboard page. Polls
/// `/api/proxy-reachable` every 2s and renders at most one of:
///
/// - RED `unreachable`: TCP probe failed — proxy is down.
/// - AMBER `shutting_down`: proxy received SIGTERM/SIGINT and is draining
///   in-flight requests. /readyz returns 503 with `failed_checks: ["shutting_down"]`.
///   K8s pulls the instance from rotation; the dashboard surfaces it so a
///   human watching can see "this is mid-deploy, not crashed."
/// - YELLOW `no persistence`: proxy up AND /readyz reports
///   `postgres_not_configured` — operator forgot the DB env var; events
///   won't appear in the dashboard.
///
/// States are mutually exclusive by construction and ordered by urgency
/// (unreachable > shutting_down > no_persistence > healthy).
export function ProxyReachabilityBanner() {
  const [state, setState] = useState<State | null>(null);
  // Track previous display state to surface a transient "reconnected" toast
  // when transitioning out of a degraded state. Silent on first probe.
  const prevDisplay = useRef<DisplayState | null>(null);
  const [reconnected, setReconnected] = useState(false);
  // Client-side seconds-since-last-poll, so the drain countdown ticks every
  // second instead of stepping by the poll interval (2s). Reset on each
  // successful probe.
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function probe() {
      try {
        const res = await fetch("/api/proxy-reachable", { cache: "no-store" });
        if (!res.ok || cancelled) return;
        const body = (await res.json()) as State;
        if (cancelled) return;
        const next = classify(body);
        const prev = prevDisplay.current;
        if (
          prev !== null &&
          prev !== "healthy" &&
          prev !== "reconnected" &&
          next === "healthy"
        ) {
          setReconnected(true);
          setTimeout(() => setReconnected(false), 4000);
        }
        prevDisplay.current = next;
        setState(body);
        setTick(0);
      } catch {
        // dashboard-api may itself be down; that surfaces via the page's
        // own error boundaries, not here.
      }
    }
    probe();
    const pollTimer = setInterval(probe, 2000);
    const tickTimer = setInterval(() => setTick((t) => t + 1), 1000);
    return () => {
      cancelled = true;
      clearInterval(pollTimer);
      clearInterval(tickTimer);
    };
  }, []);

  if (!state) return null;

  const display = classify(state);

  if (display === "unreachable") {
    return (
      <div className="mb-4 border border-accent-danger/40 bg-accent-danger/5 text-accent-danger text-sm rounded-md px-4 py-3 flex items-center gap-3">
        <span className="inline-block h-2 w-2 rounded-full bg-accent-danger" />
        <div>
          <b>Proxy unreachable</b>{" "}
          <span className="font-mono">{state.probed}</span>. Numbers on this
          page may be stale until the proxy comes back. See{" "}
          <a className="underline" href="/health">/health</a> for details.
        </div>
      </div>
    );
  }

  if (display === "shutting_down") {
    const serverRemaining = state.readyz?.shutdown_remaining_secs;
    const timeout = state.readyz?.shutdown_timeout_secs;
    const remaining =
      typeof serverRemaining === "number"
        ? Math.max(0, serverRemaining - tick)
        : null;
    return (
      <div className="mb-4 border border-accent-warn/40 bg-accent-warn/10 text-accent-warn text-sm rounded-md px-4 py-3 flex items-center gap-3">
        <span className="inline-block h-2 w-2 rounded-full bg-accent-warn animate-pulse" />
        <div className="flex-1">
          <b>Proxy is shutting down.</b> Drain in progress; new requests rejected.
          {" "}
          <a className="underline" href="/health">/health</a>
        </div>
        {remaining !== null && (
          <div className="font-mono text-base tabular-nums flex flex-col items-end leading-tight">
            <span>{remaining}s</span>
            {typeof timeout === "number" && (
              <span className="text-[10px] uppercase tracking-wider opacity-70">
                of {timeout}s
              </span>
            )}
          </div>
        )}
      </div>
    );
  }

  if (display === "no_db") {
    return (
      <div className="mb-4 border border-accent-warn/40 bg-accent-warn/5 text-accent-warn text-sm rounded-md px-4 py-3 flex items-center gap-3">
        <span className="inline-block h-2 w-2 rounded-full bg-accent-warn" />
        <div>
          <b>Proxy is running without <code className="font-mono">CASCADIA_DATABASE_URL</code>.</b>{" "}
          Events from this proxy instance will not appear in Recent activity or
          on Pareto — they&apos;re only written to the proxy&apos;s stdout. Set
          the env var and restart the proxy to enable persistence.
        </div>
      </div>
    );
  }

  // Healthy path. Show a transient "reconnected" toast when we just left a
  // degraded state, then fade to nothing.
  if (reconnected) {
    return (
      <div className="mb-4 border border-accent/40 bg-accent/5 text-accent text-sm rounded-md px-4 py-2 flex items-center gap-3 transition-opacity">
        <span className="inline-block h-2 w-2 rounded-full bg-accent" />
        <div>
          <b>Proxy reconnected</b> — live data is flowing again.
        </div>
      </div>
    );
  }
  return null;
}
