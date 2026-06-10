// Recent activity page — tail of the proxy event log + the latest judge
// verdicts, side by side. Server component; api.recentEvents() /
// recentVerdicts() via lib/api, rendered inside Shell.
import { ProxyLivePipServer } from "@/components/ProxyLivePipServer";
import { Shell } from "@/components/Shell";
import { api } from "@/lib/api";
import { pct } from "@/lib/format";

export const revalidate = 5;
export const dynamic = "force-dynamic";
export const metadata = { title: "Recent activity" };

export default async function ActivityPage() {
  let events;
  let verdicts;
  let error: string | null = null;
  try {
    [events, verdicts] = await Promise.all([
      api.recentEvents(30),
      api.recentVerdicts(30),
    ]);
  } catch (err) {
    error = (err as Error).message;
  }
  // Proxy reachability + no-DB warnings live in ProxyReachabilityBanner
  // (rendered by Shell on every page); they're client-polled so they stay
  // in sync with proxy state without dragging this page's cache TTL down.
  return (
    <Shell active="/activity" headerSlot={<ProxyLivePipServer />}>
      <h1 className="text-2xl font-semibold tracking-tight">Recent activity</h1>
      <p className="text-fg-muted text-sm mt-1">
        Tail of the event log + the latest judge verdicts. Status column
        legend: <span className="text-fg-muted">cheap</span> = cascade
        accepted the cheap tier;{" "}
        <span className="text-accent-warn">escalated</span> = cascade
        rejected the cheap tier and routed to expensive;{" "}
        <span className="text-accent">tool-use</span> = inbound request
        carried <code>tools=[...]</code>, cascade bypassed escalation by
        design (Phase 7.1).
      </p>
      {error && (
        <div className="mt-4 border border-accent-danger/40 bg-accent-danger/5 text-accent-danger text-sm rounded-md px-4 py-3">
          <b>Couldn&apos;t load activity:</b> {error}
        </div>
      )}
      <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-3">
        <div className="border border-border rounded-md overflow-hidden">
          <h2 className="bg-bg-surface px-4 py-2 text-xs uppercase tracking-wider text-fg-muted font-normal m-0">
            Proxy events
          </h2>
          <table className="w-full text-xs font-mono">
            <thead className="sr-only">
              <tr>
                <th scope="col">Time</th>
                <th scope="col">Cluster</th>
                <th scope="col">Model</th>
                <th scope="col">Status</th>
                <th scope="col">Latency</th>
              </tr>
            </thead>
            <tbody>
              {events?.map((e) => {
                // Three distinct routing outcomes — render them differently
                // so an operator looking at the log can spot why each row was
                // served the way it was. Tool-use bypass is a separate
                // signal from "the cheap tier was confident enough."
                let status: React.ReactNode;
                if (e.tools_present) {
                  status = (
                    <span
                      className="text-accent"
                      title="cascade bypassed escalation: inbound request carried tools=[...] (Phase 7.1)"
                    >
                      tool-use
                    </span>
                  );
                } else if (e.escalated) {
                  status = (
                    <span className="text-accent-warn">escalated</span>
                  );
                } else {
                  status = <span className="text-fg-muted">cheap</span>;
                }
                return (
                  <tr key={e.request_id} className="border-t border-border">
                    <td className="px-3 py-1.5 text-fg-muted">
                      {new Date(e.occurred_at).toLocaleTimeString()}
                    </td>
                    <td className="px-3 py-1.5">{e.cluster_id ?? "—"}</td>
                    <td className="px-3 py-1.5">{e.model ?? "—"}</td>
                    <td className="px-3 py-1.5">{status}</td>
                    <td className="px-3 py-1.5 text-right text-fg-muted">
                      {e.elapsed_ms}ms
                    </td>
                  </tr>
                );
              })}
              {events && events.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-3 py-6 text-fg-muted text-center">
                    No events yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="border border-border rounded-md overflow-hidden">
          <h2 className="bg-bg-surface px-4 py-2 text-xs uppercase tracking-wider text-fg-muted font-normal m-0">
            Judge verdicts
          </h2>
          <table className="w-full text-xs font-mono">
            <thead className="sr-only">
              <tr>
                <th scope="col">Time</th>
                <th scope="col">Judge</th>
                <th scope="col">Cluster</th>
                <th scope="col">Score</th>
              </tr>
            </thead>
            <tbody>
              {verdicts?.map((v) => (
                <tr key={v.score_id} className="border-t border-border">
                  <td className="px-3 py-1.5 text-fg-muted">
                    {new Date(v.occurred_at).toLocaleTimeString()}
                  </td>
                  <td className="px-3 py-1.5">{v.judge_name}</td>
                  <td className="px-3 py-1.5 text-fg-muted">
                    {v.cluster_id ?? "—"}
                  </td>
                  <td className="px-3 py-1.5 text-right text-accent">
                    {pct(v.score, 0)}
                  </td>
                </tr>
              ))}
              {verdicts && verdicts.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-3 py-6 text-fg-muted text-center">
                    No verdicts yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </Shell>
  );
}
