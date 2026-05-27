import { ParetoChart } from "@/components/ParetoChart";
import { ProxyLivePipServer } from "@/components/ProxyLivePipServer";
import { Shell } from "@/components/Shell";
import { api } from "@/lib/api";

export const revalidate = 10;
export const dynamic = "force-dynamic";
export const metadata = { title: "Pareto frontier" };

export default async function ParetoPage() {
  let points;
  let error: string | null = null;
  try {
    points = await api.pareto();
  } catch (err) {
    error = (err as Error).message;
  }
  return (
    <Shell active="/pareto" headerSlot={<ProxyLivePipServer />}>
      <h1 className="text-2xl font-semibold tracking-tight">Pareto frontier</h1>
      <p className="text-fg-muted text-sm mt-1">
        Each dot is one cluster&apos;s current operating point.{" "}
        <b>Top-left is good</b> (high quality, low cost);{" "}
        <b>bottom-right is bad</b> (high cost, low quality).
      </p>
      <p className="text-fg-muted text-xs mt-1">
        X-axis = escalation rate (fraction of requests that went to the
        expensive tier — a cost proxy). Y-axis = mean judge score on
        shadow-routed pairs. Dot size = sample count. <b>Clusters with high
        tool-use traffic will plot at or near X=0%</b> — cascade bypasses
        escalation on tool-use requests (Phase 7.1), so those clusters are
        cost-anchored at the cheap tier by design, not by the controller
        deciding to never escalate. The <a className="text-accent hover:underline" href="/clusters">Clusters page</a> shows the Tool-use rate per cluster.
      </p>
      {error && (
        <div className="mt-4 border border-accent-danger/40 bg-accent-danger/5 text-accent-danger text-sm rounded-md px-4 py-3">
          <b>Couldn&apos;t load Pareto data:</b> {error}
        </div>
      )}
      {points && points.length === 0 && (
        <div className="mt-6 border border-border rounded-md bg-bg-surface text-fg-muted text-sm px-6 py-16 text-center">
          <div className="text-fg text-base font-medium mb-2">No data yet</div>
          <div>
            No scored shadow pairs in the last 7 days. To populate:
          </div>
          <ol className="mt-3 inline-block text-left text-xs font-mono space-y-1">
            <li>1. Send chat requests through the proxy at <code>:8080</code></li>
            <li>2. Wait for the judge worker to score the shadow pairs</li>
            <li>3. Reload this page</li>
          </ol>
          <div className="mt-3 text-xs">
            Or run <code className="font-mono">bench/scripts/pareto-frontier.sh</code> for a one-shot synthetic seed.
          </div>
        </div>
      )}
      {points && points.length > 0 && (
        <div className="mt-6">
          <ParetoChart points={points} />
          <div className="mt-4 text-xs text-fg-muted">
            Read this as: bottom-right is bad (high cost, low quality); top-left
            is good (low cost, high quality). The honest frontier needs hundreds
            of pairs per cluster — this is the live operating point only.
          </div>
        </div>
      )}
    </Shell>
  );
}
