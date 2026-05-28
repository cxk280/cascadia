// Pareto-frontier fit + projection (claim 2.3 — the navigable frontier).
//
// Given the live per-cluster operating points (escalation rate = cost proxy,
// mean ensemble quality), we:
//   1. keep the Pareto-efficient envelope (non-dominated points),
//   2. expose a monotone projection quality → cost so a slider can answer
//      "I want X% of best-tier quality — what will it cost?", and
//   3. back-test the fit against the real points via leave-one-out: hold a
//      cluster out, predict its cost from its quality using the rest, and
//      check whether the prediction lands inside the measured escalation's
//      95% Wilson interval. That turns "trust the curve" into a measured
//      coverage number instead of a claim.
//
// Pure + dependency-free so it's trivially testable and runs on the server
// (the page is a server component) or the client (the slider).

import type { ParetoPoint } from "@/lib/api";

export interface FrontierPoint {
  cluster_id: string;
  escalation_rate: number; // cost proxy, [0, 1]
  mean_quality: number; // [0, 1]
  sample_size: number;
}

export interface Interval {
  lo: number;
  hi: number;
}

export interface BacktestRow {
  cluster_id: string;
  quality: number;
  measured_cost: number;
  predicted_cost: number | null;
  ci: Interval; // 95% Wilson interval on the measured escalation rate
  within: boolean;
}

export interface Backtest {
  rows: BacktestRow[];
  /** Fraction of evaluated clusters whose predicted cost fell within the CI. */
  coverage: number;
  /** True when every evaluated cluster's prediction landed within its CI. */
  validated: boolean;
  /** Number of clusters that could be evaluated (need ≥2 others to fit). */
  evaluated: number;
}

/** Highest measured quality — the "best tier" the slider expresses a % of. */
export function bestTierQuality(points: ParetoPoint[]): number {
  return points.reduce((m, p) => Math.max(m, p.mean_quality), 0);
}

/** Lowest measured quality — the floor of the achievable range. */
export function worstTierQuality(points: ParetoPoint[]): number {
  if (points.length === 0) return 0;
  return points.reduce((m, p) => Math.min(m, p.mean_quality), 1);
}

/**
 * Pareto-efficient envelope: a point is dominated if some other point has
 * quality ≥ and escalation (cost) ≤ (strictly better on at least one axis).
 * Keep the non-dominated points — the honest frontier.
 */
export function paretoEfficient(points: ParetoPoint[]): FrontierPoint[] {
  const efficient = points.filter((p) => {
    return !points.some(
      (q) =>
        q !== p &&
        q.mean_quality >= p.mean_quality &&
        q.escalation_rate <= p.escalation_rate &&
        (q.mean_quality > p.mean_quality || q.escalation_rate < p.escalation_rate),
    );
  });
  // Sort by cost ascending; quality is non-decreasing along an efficient
  // frontier so this also sorts by quality ascending.
  return efficient
    .map((p) => ({
      cluster_id: p.cluster_id,
      escalation_rate: p.escalation_rate,
      mean_quality: p.mean_quality,
      sample_size: p.sample_size,
    }))
    .sort((a, b) => a.escalation_rate - b.escalation_rate);
}

/**
 * Project the cost (escalation rate) required to reach a target quality, by
 * piecewise-linear interpolation along the efficient frontier. Below the
 * frontier's quality range we return the cheapest point's cost; above it, the
 * most-expensive point's cost (you can't buy more quality than the data shows).
 * Returns null when there's no frontier to fit.
 */
export function projectCostForQuality(
  frontier: FrontierPoint[],
  qualityTarget: number,
): number | null {
  if (frontier.length === 0) return null;
  // Sort by quality ascending for the quality→cost lookup.
  const byQuality = [...frontier].sort((a, b) => a.mean_quality - b.mean_quality);
  if (byQuality.length === 1) return byQuality[0].escalation_rate;

  const first = byQuality[0];
  const last = byQuality[byQuality.length - 1];
  if (qualityTarget <= first.mean_quality) return first.escalation_rate;
  if (qualityTarget >= last.mean_quality) return last.escalation_rate;

  for (let i = 0; i < byQuality.length - 1; i++) {
    const a = byQuality[i];
    const b = byQuality[i + 1];
    if (qualityTarget >= a.mean_quality && qualityTarget <= b.mean_quality) {
      const span = b.mean_quality - a.mean_quality;
      if (span <= 0) return a.escalation_rate;
      const t = (qualityTarget - a.mean_quality) / span;
      return a.escalation_rate + t * (b.escalation_rate - a.escalation_rate);
    }
  }
  return last.escalation_rate;
}

/**
 * 95% Wilson score interval for a binomial proportion (here: escalation rate
 * over `n` requests). Wilson behaves under small n far better than the normal
 * approximation, which matters because some clusters have few shadow pairs.
 */
export function wilsonInterval(p: number, n: number, z = 1.96): Interval {
  if (n <= 0) return { lo: 0, hi: 1 };
  const z2 = z * z;
  const denom = 1 + z2 / n;
  const center = (p + z2 / (2 * n)) / denom;
  const margin = (z * Math.sqrt((p * (1 - p)) / n + z2 / (4 * n * n))) / denom;
  return {
    lo: Math.max(0, center - margin),
    hi: Math.min(1, center + margin),
  };
}

/**
 * Leave-one-out back-test of the frontier fit against the real operating
 * points. For each cluster we re-fit the frontier on the *other* clusters,
 * predict the held-out cluster's cost from its measured quality, and check the
 * prediction against the measured escalation's 95% CI. No extra traffic
 * needed — this validates the curve against data already collected. (The
 * stronger form — drive real traffic at three brand-new predicted policies —
 * is what bench/scripts/mtbench-humaneval.sh produces once you spend the
 * tokens; this is the always-available self-consistency check.)
 */
export function leaveOneOutBacktest(points: ParetoPoint[]): Backtest {
  const rows: BacktestRow[] = [];
  for (const held of points) {
    const others = points.filter((p) => p !== held);
    const frontier = paretoEfficient(others);
    if (frontier.length < 2) continue; // not enough to fit a curve
    const predicted = projectCostForQuality(frontier, held.mean_quality);
    const ci = wilsonInterval(held.escalation_rate, held.sample_size);
    const within =
      predicted !== null && predicted >= ci.lo && predicted <= ci.hi;
    rows.push({
      cluster_id: held.cluster_id,
      quality: held.mean_quality,
      measured_cost: held.escalation_rate,
      predicted_cost: predicted,
      ci,
      within,
    });
  }
  const evaluated = rows.length;
  const withinCount = rows.filter((r) => r.within).length;
  return {
    rows,
    evaluated,
    coverage: evaluated > 0 ? withinCount / evaluated : 0,
    validated: evaluated > 0 && withinCount === evaluated,
  };
}
