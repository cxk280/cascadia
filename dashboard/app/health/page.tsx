import { ProxyLivePipServer } from "@/components/ProxyLivePipServer";
import { Shell } from "@/components/Shell";
import { api, type ConfigSnapshot } from "@/lib/api";

// Health page is the on-call signal — stale data is worse than slow data.
// dynamic = 'force-dynamic' disables the route cache so every page load
// hits dashboard-api fresh; the proxy-reachable TCP probe is itself <1s.
export const dynamic = "force-dynamic";
export const revalidate = 0;
export const metadata = { title: "Health" };

export default async function HealthPage() {
  // Probe proxy reachability + overview metrics + the data-residency config
  // snapshot independently so each can fail without bringing down the page.
  const [overviewResult, reachableResult, configResult] = await Promise.allSettled([
    api.overview(15),
    api.proxyReachable(),
    api.config(),
  ]);

  const overview =
    overviewResult.status === "fulfilled" ? overviewResult.value : undefined;
  const overviewError =
    overviewResult.status === "rejected"
      ? (overviewResult.reason as Error).message
      : null;

  const reachable =
    reachableResult.status === "fulfilled"
      ? reachableResult.value
      : { reachable: false, probed: "unknown", error: "probe failed" };

  const config =
    configResult.status === "fulfilled" ? configResult.value : undefined;

  return (
    <Shell active="/health" headerSlot={<ProxyLivePipServer />}>
      <a
        href="/"
        className="text-xs text-fg-muted hover:text-fg inline-block mb-3"
      >
        ← Back to Overview
      </a>
      <h1 className="text-2xl font-semibold tracking-tight">Health</h1>
      <p className="text-fg-muted text-sm mt-1">
        Last 15 minutes. Each row is a service-level signal you&apos;d page on.
        Looking for the data-residency posture for a GDPR/DSAR response?{" "}
        <a className="text-accent hover:underline" href="#data-residency">
          Jump to Data residency ↓
        </a>
      </p>
      {overviewError && (
        <div className="mt-6 border border-accent-danger/40 bg-accent-danger/5 text-accent-danger text-sm rounded-md px-4 py-3">
          <b>Couldn&apos;t load health data:</b> {overviewError}
        </div>
      )}
      <div className="mt-6 border border-border rounded-md overflow-hidden">
        <table className="w-full text-sm">
          <tbody>
            <Row
              label="Proxy reachable"
              value={
                reachable.reachable
                  ? `${reachable.probed} ✓`
                  : `${reachable.probed} unreachable`
              }
              ok={reachable.reachable}
            />
            {overview && (
              <>
                <Row
                  label="Proxy throughput (last 15m)"
                  value={`${overview.request_count.toLocaleString()} req`}
                  // If unreachable we already paged on row 1 — don't
                  // double-page here. If reachable and zero traffic, gray
                  // ("no traffic" is fine for a healthy idle deployment).
                  ok={
                    !reachable.reachable
                      ? null
                      : overview.request_count > 0
                        ? true
                        : null
                  }
                />
                <Row
                  label="Success rate"
                  value={
                    overview.success_rate == null
                      ? "—"
                      : `${(overview.success_rate * 100).toFixed(1)}%`
                  }
                  ok={
                    overview.success_rate == null
                      ? null
                      : overview.success_rate >= 0.99
                  }
                />
                <Row
                  label="Avg latency"
                  value={
                    overview.avg_latency_ms == null
                      ? "—"
                      : overview.avg_latency_ms < 1000
                        ? `${overview.avg_latency_ms.toFixed(0)} ms`
                        : `${(overview.avg_latency_ms / 1000).toFixed(2)} s`
                  }
                  ok={
                    overview.avg_latency_ms == null
                      ? null
                      : overview.avg_latency_ms < 30_000
                  }
                />
                <Row
                  label="Judge sample size"
                  value={overview.judge_sample_size.toString()}
                  ok={overview.judge_sample_size > 0}
                />
              </>
            )}
          </tbody>
        </table>
      </div>
      <p className="text-fg-muted text-xs mt-3">
        Set <code className="font-mono">CASCADIA_PROXY_URL</code> on
        dashboard-api to point this probe at the proxy in your deployment
        (default: <code className="font-mono">http://127.0.0.1:8080</code>).
      </p>

      {/* Data-residency posture — what GDPR / DSAR responses anchor on. */}
      <h2
        id="data-residency"
        className="text-lg font-semibold tracking-tight mt-8 scroll-mt-16"
      >
        Data residency
      </h2>
      <p className="text-fg-muted text-sm mt-1">
        What this deploy persists. Drives your GDPR / DSAR response — see{" "}
        <a
          className="text-accent hover:underline"
          href="https://github.com/cascadia-llm/cascadia/blob/main/SECURITY.md#data-residency-at-a-glance"
        >
          SECURITY.md → Data residency
        </a>{" "}
        for the three postures and the deletion runbook.
      </p>
      <div className="mt-3 border border-border rounded-md overflow-hidden">
        <table className="w-full text-sm">
          <tbody>
            <Row
              label="Posture"
              value={postureLabel(config)}
              ok={postureOk(config)}
            />
            <Row
              label="events.request_body / response_body persisted"
              value={
                config?.data_residency
                  ? config.data_residency.persist_bodies
                    ? "yes (verbatim)"
                    : "no (CASCADIA_PERSIST_BODIES=false)"
                  : "—"
              }
              ok={null}
            />
            <Row
              label="shadow_pairs prompt + responses redacted"
              value={
                config?.data_residency
                  ? config.data_residency.redact_shadow_bodies
                    ? "yes (sha256 digest)"
                    : "no (verbatim)"
                  : "—"
              }
              ok={null}
            />
            <Row
              label="Shadow eval active on any cluster"
              value={
                config?.data_residency
                  ? config.data_residency.any_shadow_rate_active
                    ? "yes"
                    : "no (all shadow_rate=0)"
                  : "—"
              }
              ok={null}
            />
            <Row
              label="Proxy bearer-token auth enabled"
              value={
                config?.auth?.bearer_required ? "yes" : "no (open /v1/*)"
              }
              ok={null}
            />
          </tbody>
        </table>
      </div>
    </Shell>
  );
}

function postureLabel(config?: ConfigSnapshot): string {
  const p = config?.data_residency?.posture;
  if (!p) return "unknown";
  const labels: Record<string, string> = {
    full_persistence: "Full persistence (verbatim prompts + responses in shadow_pairs)",
    redacted: "Redacted (sha256 digest of shadow text)",
    shadow_disabled: "Shadow eval disabled (no shadow_pairs written)",
  };
  // A posture string the dashboard doesn't recognize (schema drift / a new
  // server-side posture) should render explicitly rather than as a blank cell
  // on the page operators consult for DSAR posture.
  return labels[p] ?? `unknown (${p})`;
}

function postureOk(config?: ConfigSnapshot): boolean | null {
  // We don't say one posture is "right" — operators pick based on their
  // regulatory context. Always render gray; the value tells you what's on.
  if (!config?.data_residency) return null;
  return null;
}

function Row({
  label,
  value,
  ok,
}: {
  label: string;
  value: string;
  ok: boolean | null;
}) {
  const dot =
    ok === null
      ? "bg-fg-subtle"
      : ok
        ? "bg-accent"
        : "bg-accent-danger";
  return (
    <tr className="border-t border-border first:border-t-0">
      <td className="px-4 py-3 w-2/3">{label}</td>
      <td className="px-4 py-3 font-mono text-right">{value}</td>
      <td className="px-4 py-3 w-12">
        <span className={`inline-block h-2 w-2 rounded-full ${dot}`} />
      </td>
    </tr>
  );
}
