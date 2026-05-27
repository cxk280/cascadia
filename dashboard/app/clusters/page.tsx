import { InfoTip } from "@/components/InfoTip";
import { ProxyLivePipServer } from "@/components/ProxyLivePipServer";
import { Shell } from "@/components/Shell";
import { api, type ClusterPolicy, type PolicyTable } from "@/lib/api";

export const revalidate = 10;
export const dynamic = "force-dynamic";
export const metadata = { title: "Clusters" };

function pct(value: number | null): string {
  if (value == null) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function num(value: number | null | undefined, digits = 2): string {
  if (value == null) return "—";
  return value.toFixed(digits);
}

/// Threshold above which the escalation rate gets a caveat. If most of a
/// cluster's traffic carries `tools=[...]`, escalation will be near-zero by
/// design (Phase 7.1 bypass) and the headline number reads as "broken" without
/// this context.
const HIGH_TOOL_USE_THRESHOLD = 0.5;

function providerPair(
  cheap: string | null,
  expensive: string | null,
): { label: string; mixed: boolean } {
  if (!cheap && !expensive) return { label: "—", mixed: false };
  if (cheap && expensive && cheap !== expensive) {
    return { label: `${cheap} → ${expensive}`, mixed: true };
  }
  return { label: cheap ?? expensive ?? "—", mixed: false };
}

export default async function ClustersPage() {
  let rows;
  let policyByCluster: Record<string, ClusterPolicy> = {};
  let policyVersion: string | null = null;
  let error: string | null = null;
  try {
    const [clusters, policy] = await Promise.all([
      api.clusters(),
      api.policy(),
    ]);
    rows = clusters;
    if (policy && "clusters" in policy) {
      const table = policy as PolicyTable;
      policyByCluster = table.clusters;
      policyVersion = table.version ?? null;
    }
  } catch (err) {
    error = (err as Error).message;
  }
  return (
    <Shell active="/clusters" headerSlot={<ProxyLivePipServer />}>
      <h1 className="text-2xl font-semibold tracking-tight">Clusters</h1>
      <p className="text-fg-muted text-sm mt-1">
        Per-cluster traffic + escalation + scored quality + live policy
        (threshold + shadow_rate). The Escalation column excludes tool-use
        and streaming traffic — cascade bypasses escalation on both paths
        by design (Phase 7.1 + 7.2). The Tool-use column shows how much of
        the cluster's traffic is on that bypass path.{" "}
        {policyVersion && (
          <span>
            Policy version:{" "}
            <code className="text-fg">{policyVersion}</code>.
          </span>
        )}
      </p>
      {error && (
        <div className="mt-4 border border-accent-danger/40 bg-accent-danger/5 text-accent-danger text-sm rounded-md px-4 py-3">
          <b>Couldn&apos;t load clusters:</b> {error}
        </div>
      )}
      {rows && (
        <div className="mt-6 border border-border rounded-md overflow-x-auto">
          <table className="w-full text-sm min-w-[720px]">
            <thead className="bg-bg-surface text-fg-muted text-xs uppercase tracking-wider">
              <tr>
                <th scope="col" className="text-left px-4 py-2">Cluster</th>
                <th scope="col" className="text-left px-4 py-2">Providers</th>
                <th scope="col" className="text-right px-4 py-2">Requests</th>
                <th scope="col" className="text-right px-4 py-2">
                  <span className="inline-flex items-center justify-end gap-1">
                    <InfoTip label="Escalation">
                      Fraction of cascade decisions that escalated cheap → expensive.
                      <strong className="block mt-1 text-fg">
                        Excludes tool-use and streaming traffic
                      </strong>
                      — cascade bypasses escalation on both paths by design
                      (Phase 7.1 / 7.2). A 0% escalation cluster is normal if
                      its Tool-use rate is high.
                    </InfoTip>
                  </span>
                </th>
                <th scope="col" className="text-right px-4 py-2">
                  <span className="inline-flex items-center justify-end gap-1">
                    <InfoTip label="Tool-use">
                      Fraction of requests on this cluster that carried
                      <code className="px-1">tools=[...]</code>. Cascade
                      bypasses escalation on these. If this column is near
                      100%, the Escalation column will be near 0% — not a bug.
                    </InfoTip>
                  </span>
                </th>
                <th scope="col" className="text-right px-4 py-2">
                  <span className="inline-flex items-center justify-end gap-1">
                    <InfoTip label="Threshold" align="left">
                      Cheap-tier confidence floor. The cheap response is
                      accepted when its confidence is{" "}
                      <strong className="text-fg">≥ threshold</strong>;
                      otherwise the cascade escalates to expensive.{" "}
                      <strong className="block mt-1 text-fg">
                        Lower threshold = lower bar = more cheap accepted = LESS escalation = cheaper.
                      </strong>{" "}
                      Range 0.0–1.0. Refit by the policy controller from
                      judge scores; you can also pin a value in the policy
                      JSON.
                    </InfoTip>
                  </span>
                </th>
                <th scope="col" className="text-right px-4 py-2">
                  <span className="inline-flex items-center justify-end gap-1">
                    <InfoTip label="Shadow rate" align="left">
                      Fraction of accepted-cheap responses that are mirrored
                      to the expensive tier in the background to feed the
                      judge.{" "}
                      <strong className="block mt-1 text-fg">
                        ⚠ Costs real money — fires an expensive-tier API call
                        on this fraction of traffic.
                      </strong>{" "}
                      Default 0.05–0.10 is the sweet spot; 0.0 disables the
                      closed loop entirely.
                    </InfoTip>
                  </span>
                </th>
                <th scope="col" className="text-right px-4 py-2">Mean score</th>
                <th scope="col" className="text-right px-4 py-2">Sample size</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr>
                  <td colSpan={9} className="text-center text-fg-muted px-4 py-6">
                    No traffic in the last 7 days.
                  </td>
                </tr>
              )}
              {rows.map((row) => {
                const pair = providerPair(row.cheap_provider, row.expensive_provider);
                const highToolUse =
                  row.tools_use_rate != null &&
                  row.tools_use_rate > HIGH_TOOL_USE_THRESHOLD;
                const policy = policyByCluster[row.cluster_id];
                return (
                  <tr
                    key={row.cluster_id}
                    className="border-t border-border hover:bg-bg-raised/50"
                  >
                    <td className="px-4 py-2 font-mono text-fg">{row.cluster_id}</td>
                    <td className="px-4 py-2 font-mono text-xs">
                      {pair.mixed ? (
                        <span className="text-accent">{pair.label}</span>
                      ) : (
                        <span className="text-fg-muted">{pair.label}</span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-right font-mono">
                      {row.request_count.toLocaleString()}
                    </td>
                    <td className="px-4 py-2 text-right font-mono">
                      {highToolUse && (
                        <span
                          className="text-accent-warn mr-1"
                          title={`high tool-use cluster: ${pct(row.tools_use_rate)} of traffic bypasses escalation by design`}
                        >
                          ⚠
                        </span>
                      )}
                      {pct(row.escalation_rate)}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-fg-muted">
                      {pct(row.tools_use_rate)}
                    </td>
                    <td className="px-4 py-2 text-right font-mono">
                      {num(policy?.threshold)}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-fg-muted">
                      {num(policy?.shadow_rate)}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-accent">
                      {pct(row.mean_judge_score)}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-fg-muted">
                      {row.judge_sample_size}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Shell>
  );
}
