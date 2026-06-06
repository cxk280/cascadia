// Server-side fetchers for the cascadia-dashboard-api. We call this from
// `app/` server components so the dashboard renders fully on the server
// and the dashboard-api never has to be exposed to the public internet.

const API_BASE =
  process.env.CASCADIA_DASHBOARD_API_BASE ?? "http://127.0.0.1:18082";

async function fetchJson<T>(
  path: string,
  options: { revalidate?: number; cache?: RequestCache } = {},
): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    headers: { Accept: "application/json" },
    next: { revalidate: options.revalidate ?? 10 },
    cache: options.cache,
  });
  if (!res.ok) {
    const op = path.split("?")[0];
    throw new Error(`${op} returned HTTP ${res.status} ${res.statusText}`);
  }
  return (await res.json()) as T;
}

export interface Overview {
  window_seconds: number;
  request_count: number;
  avg_latency_ms: number | null;
  escalation_rate: number | null;
  // Fraction of requests in the window that carried `tools=[...]`. Cascade
  // bypasses escalation on those, so this caveats a low escalation_rate.
  tools_use_rate: number | null;
  success_rate: number | null;
  mean_judge_score: number | null;
  judge_sample_size: number;
}

export interface ClusterRow {
  cluster_id: string;
  request_count: number;
  escalation_rate: number | null;
  mean_judge_score: number | null;
  judge_sample_size: number;
  cheap_provider: string | null;
  expensive_provider: string | null;
  tools_use_rate: number | null;
}

export interface EventRow {
  request_id: string;
  occurred_at: string;
  route: string | null;
  provider: string | null;
  model: string | null;
  upstream_status: number | null;
  elapsed_ms: number;
  cluster_id: string | null;
  escalated: boolean;
  // True if the inbound request carried `tools=[...]`. Cascade bypassed
  // escalation on these — the row's `escalated: false` is by design.
  tools_present: boolean;
}

export interface RecentVerdict {
  score_id: string;
  pair_id: string;
  judge_name: string;
  prompt_variant: string;
  score: number;
  confidence: number | null;
  occurred_at: string;
  cluster_id: string | null;
  cheap_model: string | null;
  expensive_model: string | null;
}

export interface ParetoPoint {
  cluster_id: string;
  escalation_rate: number;
  mean_quality: number;
  sample_size: number;
}

// Dashboard reads default to a 7-day window so demos and stale-data
// demo reviews still render the real numbers. The dashboard-api
// itself still accepts any window_minutes ∈ [1, 10080].
export const DEFAULT_WINDOW_MINUTES = 10080;
export const DEFAULT_WINDOW_LABEL = "Last 7 days";

export interface ReadyzPayload {
  status: string;
  service: string;
  version: string;
  passed_checks?: string[];
  failed_checks?: string[];
}

export interface ProxyReachable {
  reachable: boolean;
  probed: string;
  error?: string;
  readyz?: ReadyzPayload;
}

export interface ConfigSnapshot {
  version?: string;
  data_residency?: {
    posture: "full_persistence" | "redacted" | "shadow_disabled";
    persist_bodies: boolean;
    redact_shadow_bodies: boolean;
    any_shadow_rate_active: boolean;
  };
  auth?: {
    bearer_required: boolean;
  };
  policy_version?: string | null;
  policy_cluster_count?: number;
  error?: string;
}

export interface ClusterPolicy {
  cluster_id: string;
  cheap_model: string;
  expensive_model: string;
  threshold: number;
  shadow_rate: number;
}

export interface PolicyTable {
  default_cluster: string;
  version?: string | null;
  cluster_buckets?: number;
  clusters: Record<string, ClusterPolicy>;
}

export const api = {
  overview: (windowMinutes = DEFAULT_WINDOW_MINUTES) =>
    fetchJson<Overview>(`/api/overview?window_minutes=${windowMinutes}`),
  clusters: (windowMinutes = DEFAULT_WINDOW_MINUTES) =>
    fetchJson<ClusterRow[]>(`/api/clusters?window_minutes=${windowMinutes}`),
  recentEvents: (limit = 50) =>
    fetchJson<EventRow[]>(`/api/events/recent?limit=${limit}`),
  recentVerdicts: (limit = 50) =>
    fetchJson<RecentVerdict[]>(`/api/verdicts/recent?limit=${limit}`),
  pareto: (windowMinutes = DEFAULT_WINDOW_MINUTES) =>
    fetchJson<ParetoPoint[]>(`/api/pareto?window_minutes=${windowMinutes}`),
  policy: () => fetchJson<PolicyTable | { error: string }>("/api/policy"),
  config: () => fetchJson<ConfigSnapshot>("/api/config"),
  // No-store: this signal feeds the on-call health page; we never want a
  // cached "reachable=true" lingering while the proxy is actually down.
  proxyReachable: () =>
    fetchJson<ProxyReachable>("/api/proxy-reachable", { cache: "no-store" }),
};

// Re-export the API_BASE for Next.js Route Handlers that proxy
// calibration endpoints. The labeling app is interactive and must call
// from the browser, so it talks to /api/calibrate/* on this Next.js
// origin, and those handlers (under app/api/calibrate/*) forward to
// FastAPI on API_BASE. The browser never sees the FastAPI URL.
export const SERVER_API_BASE = API_BASE;
