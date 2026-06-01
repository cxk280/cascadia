"use client";

import { useMemo, useState } from "react";

import { ParetoChart } from "@/components/ParetoChart";
import type { ParetoPoint } from "@/lib/api";
import {
  bestTierQuality,
  leaveOneOutBacktest,
  paretoEfficient,
  projectCostForQuality,
  worstTierQuality,
} from "@/lib/pareto-fit";

const pct = (v: number) => `${Math.round(v * 100)}%`;

// The navigable Pareto frontier (claim 2.3): drag a target quality, read the
// projected cost off the fitted curve — and see, right below, whether that fit
// actually predicts the real per-cluster points within their measured CIs.
export function ParetoSlider({ points }: { points: ParetoPoint[] }) {
  const { frontier, best, worst, backtest, frontierCurve } = useMemo(() => {
    const frontier = paretoEfficient(points);
    return {
      frontier,
      best: bestTierQuality(points),
      worst: worstTierQuality(points),
      backtest: leaveOneOutBacktest(points),
      frontierCurve: frontier.map((p) => ({
        cost: p.escalation_rate,
        quality: p.mean_quality,
      })),
    };
  }, [points]);

  // Slider expresses a target as a % of the best measured (best-tier) quality.
  const minPct = best > 0 ? Math.max(1, Math.floor((worst / best) * 100)) : 1;
  const [pctOfBest, setPctOfBest] = useState(95);
  const clampedPct = Math.min(100, Math.max(minPct, pctOfBest));
  // The slider navigates a *quality range*. When every scored cluster sits at
  // ~the same quality (too few judged pairs yet, or all clusters share one
  // model pair so only cost — not quality — differs), worst ≈ best and the
  // range collapses to a single point. Disable it with an explanation rather
  // than render a thumb that can't move.
  const locked = !(best > 0) || minPct >= 100;

  const targetQuality = (clampedPct / 100) * best;
  const projectedCost = projectCostForQuality(frontier, targetQuality);
  const projected =
    projectedCost !== null
      ? { cost: projectedCost, quality: targetQuality }
      : null;

  return (
    <div className="space-y-6">
      <ParetoChart points={points} frontier={frontierCurve} projected={projected} />

      {/* Slider + projection readout */}
      <div className="border border-border rounded-md bg-bg-surface px-5 py-4">
        <div className="flex items-baseline justify-between gap-4 flex-wrap">
          <label htmlFor="quality-target" className="text-sm font-medium text-fg">
            I want{" "}
            <span className="text-accent font-mono">{clampedPct}%</span> of
            best-tier quality
          </label>
          <div className="text-sm text-fg-muted">
            target quality{" "}
            <span className="font-mono text-fg">{pct(targetQuality)}</span>
          </div>
        </div>
        <input
          id="quality-target"
          type="range"
          min={minPct}
          max={100}
          step={1}
          value={clampedPct}
          onChange={(e) => setPctOfBest(Number(e.target.value))}
          disabled={locked}
          className={`w-full mt-3 accent-accent ${
            locked ? "opacity-40 cursor-not-allowed" : ""
          }`}
          aria-valuetext={`${clampedPct} percent of best-tier quality`}
        />
        {locked && (
          <p className="text-xs text-fg-muted mt-2">
            The slider is fixed because there isn&apos;t a quality range to
            navigate yet: every scored cluster sits at ~the same measured
            quality. That happens when too few shadow pairs have been judged, or
            when all clusters share one model pair (so they differ in cost but
            not quality). It becomes draggable once clusters diverge in measured
            quality — e.g. when they run different cheap/expensive model pairs.
          </p>
        )}
        <div className="mt-4 grid grid-cols-2 gap-4">
          <div className="rounded-md border border-border bg-bg px-4 py-3">
            <div className="text-xs text-fg-muted">Projected cost</div>
            <div className="text-2xl font-semibold font-mono text-accent mt-1">
              {projectedCost !== null ? pct(projectedCost) : "—"}
            </div>
            <div className="text-xs text-fg-muted mt-1">
              escalation rate (fraction routed to the expensive tier)
            </div>
          </div>
          <div className="rounded-md border border-border bg-bg px-4 py-3">
            <div className="text-xs text-fg-muted">Cost vs best-tier-everywhere</div>
            <div className="text-2xl font-semibold font-mono text-fg mt-1">
              {projectedCost !== null
                ? `−${Math.round((1 - projectedCost) * 100)}%`
                : "—"}
            </div>
            <div className="text-xs text-fg-muted mt-1">
              sending every request to the expensive tier is cost = 100%
            </div>
          </div>
        </div>
        <p className="text-xs text-fg-muted mt-3">
          Projection is piecewise-linear along the fitted Pareto frontier (the
          dashed line). It is an interpolation of the live operating points, not
          a promise — the back-test below measures how well it actually holds.
        </p>
      </div>

      {/* Back-test: predicted vs measured, with CIs */}
      <BacktestPanel backtest={backtest} />
    </div>
  );
}

function BacktestPanel({
  backtest,
}: {
  backtest: ReturnType<typeof leaveOneOutBacktest>;
}) {
  if (backtest.evaluated === 0) {
    return (
      <div className="border border-border rounded-md bg-bg-surface px-5 py-4 text-sm text-fg-muted">
        <b className="text-fg">Back-test:</b> need at least 3 clusters to
        leave-one-out validate the fitted frontier. Collect more shadow-scored
        traffic (or run <code className="font-mono">bench/scripts/mtbench-humaneval.sh</code>).
      </div>
    );
  }
  return (
    <div className="border border-border rounded-md bg-bg-surface px-5 py-4">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <h2 className="text-sm font-medium text-fg">
          Frontier back-test{" "}
          <span className="text-fg-muted font-normal">
            (leave-one-out, predicted vs measured)
          </span>
        </h2>
        <span
          className={
            backtest.validated
              ? "text-xs font-mono px-2 py-1 rounded border border-accent/40 bg-accent/10 text-accent"
              : "text-xs font-mono px-2 py-1 rounded border border-accent-danger/40 bg-accent-danger/10 text-accent-danger"
          }
        >
          {backtest.validated
            ? "✓ validated within ±95% CI"
            : `${Math.round(backtest.coverage * 100)}% within ±95% CI`}
        </span>
      </div>
      <p className="text-xs text-fg-muted mt-1">
        Each cluster is held out, the frontier is re-fit on the rest, and its
        cost is predicted from its measured quality. The prediction is checked
        against the measured escalation rate&apos;s 95% Wilson interval (from its
        sample size).
      </p>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-fg-muted text-left text-xs border-b border-border">
              <th className="py-2 pr-4 font-medium">Cluster</th>
              <th className="py-2 pr-4 font-medium">Quality</th>
              <th className="py-2 pr-4 font-medium">Predicted cost</th>
              <th className="py-2 pr-4 font-medium">Measured cost (95% CI)</th>
              <th className="py-2 font-medium">Within CI</th>
            </tr>
          </thead>
          <tbody className="font-mono">
            {backtest.rows.map((r) => (
              <tr key={r.cluster_id} className="border-b border-border/50">
                <td className="py-2 pr-4 text-fg">{r.cluster_id}</td>
                <td className="py-2 pr-4 text-fg-muted">{pct(r.quality)}</td>
                <td className="py-2 pr-4 text-fg">
                  {r.predicted_cost !== null ? pct(r.predicted_cost) : "—"}
                </td>
                <td className="py-2 pr-4 text-fg-muted">
                  {pct(r.measured_cost)}{" "}
                  <span className="text-fg-muted/70">
                    [{pct(r.ci.lo)}–{pct(r.ci.hi)}]
                  </span>
                </td>
                <td className="py-2">
                  {r.within ? (
                    <span className="text-accent">✓</span>
                  ) : (
                    <span className="text-accent-danger">✗</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
