// Shared types + helpers for the proxy health probe (`/api/proxy-reachable`,
// which proxies the proxy's `/readyz`).
//
// Both the page-level ProxyReachabilityBanner and the header ProxyLivePip poll
// this endpoint every 2s. This module is the single definition of the response
// shape, the no-store fetch, and the "is the proxy draining?" predicate so the
// two stay in agreement. Each component still maps the result into its own UI
// state (the banner adds a reconnect toast + drain countdown).

export interface ReadyzPayload {
  status?: string;
  passed_checks?: string[];
  failed_checks?: string[];
  shutdown_remaining_secs?: number;
  shutdown_timeout_secs?: number;
}

export interface ProxyReachable {
  reachable: boolean;
  probed: string;
  readyz?: ReadyzPayload;
}

/** Fetch the proxy-reachable probe, bypassing the route cache. Returns `null`
 *  on a non-OK response so callers keep their previous state. */
export async function fetchProxyReachable(): Promise<ProxyReachable | null> {
  const res = await fetch("/api/proxy-reachable", { cache: "no-store" });
  if (!res.ok) return null;
  return (await res.json()) as ProxyReachable;
}

/** Whether `/readyz` reports the proxy is draining (SIGTERM graceful shutdown). */
export function isShuttingDown(readyz?: ReadyzPayload): boolean {
  return (
    readyz?.status === "shutting_down" ||
    readyz?.failed_checks?.includes("shutting_down") === true
  );
}
