// Overview page — top-line KPIs (requests, escalation rate, latency, mean
// judge score) for the last 7 days. Server component; fetches from
// dashboard-api via lib/api, rendered inside Shell.
import { KpiCard } from "@/components/KpiCard";
import { ProxyLivePipServer } from "@/components/ProxyLivePipServer";
import { Shell } from "@/components/Shell";
import { api } from "@/lib/api";
import { ms, pct } from "@/lib/format";

export const revalidate = 10;
// Force dynamic rendering: this page fetches from dashboard-api at request
// time, so Next.js shouldn't try to prerender it at build time (which would
// fail in CI/Railway where dashboard-api isn't reachable during the build).
export const dynamic = "force-dynamic";

export default async function OverviewPage() {
  let overview;
  let error: string | null = null;
  try {
    overview = await api.overview();
  } catch (err) {
    error = (err as Error).message;
  }
  return (
    <Shell active="/overview" headerSlot={<ProxyLivePipServer />}>
      <h1 className="text-2xl font-semibold tracking-tight">Overview</h1>
      <p className="text-fg-muted text-sm mt-1">
        Window: last 7 days. Metrics below revalidate every 10s — reload to force a refresh.
      </p>
      {error && (
        <div className="mt-4 border border-accent-danger/40 bg-accent-danger/5 text-accent-danger text-sm rounded-md px-4 py-3">
          <b>Couldn&apos;t load overview:</b> {error}
        </div>
      )}
      {overview && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-6">
          <KpiCard
            label="Requests"
            value={overview.request_count.toLocaleString()}
            hint="proxied in window"
          />
          <KpiCard
            label="Escalation rate"
            value={pct(overview.escalation_rate)}
            hint={
              overview.tools_use_rate != null && overview.tools_use_rate > 0.05
                ? `cheap → expensive · ${pct(overview.tools_use_rate)} of traffic is tool-use (bypasses escalation)`
                : "cheap → expensive · excludes tool-use + streaming traffic"
            }
          />
          <KpiCard
            label="Avg latency"
            value={ms(overview.avg_latency_ms)}
            hint="end-to-end"
          />
          <KpiCard
            label="Mean judge score"
            value={pct(overview.mean_judge_score)}
            hint={`n=${overview.judge_sample_size}`}
            accent
          />
        </div>
      )}
      <div className="mt-8 grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="border border-border rounded-md bg-bg-surface p-4">
          <div className="text-sm font-medium">What you&apos;re looking at</div>
          <ul className="text-sm text-fg-muted mt-2 space-y-1.5 leading-snug">
            <li>
              <b className="text-fg">Cheap-first cascade</b> — each request hits
              the cheap tier; the proxy escalates only on low confidence.
            </li>
            <li>
              <b className="text-fg">Shadow eval</b> — a fraction of accepted
              cheap responses are shadow-routed to the expensive tier so the
              judge can compare.
            </li>
            <li>
              <b className="text-fg">Closed loop</b> — judge scores feed the
              policy controller, which refits per-cluster thresholds on its own.
            </li>
            <li>
              <b className="text-fg">Tool-use / streaming bypass</b> — requests
              with <code>tools=[...]</code> (Phase 7.1) or <code>stream=true</code>{" "}
              (Phase 7.2) always serve cheap, no escalation, no shadow pair.
              Mid-loop escalation would diverge into incoherent state. The
              escalation-rate KPI excludes both paths.
            </li>
          </ul>
        </div>
        <div className="border border-border rounded-md bg-bg-surface p-4">
          <div className="text-sm font-medium">Quick links</div>
          <ul className="text-sm text-fg-muted mt-2 space-y-1">
            <li>
              <a className="text-accent hover:underline" href="/pareto">
                Pareto frontier →
              </a>{" "}
              live operating point, one dot per cluster
            </li>
            <li>
              <a className="text-accent hover:underline" href="/clusters">
                Cluster explorer →
              </a>{" "}
              per-cluster traffic + quality + thresholds
            </li>
            <li>
              <a className="text-accent hover:underline" href="/activity">
                Recent activity →
              </a>{" "}
              tail of the event log
            </li>
          </ul>
        </div>
      </div>
    </Shell>
  );
}
