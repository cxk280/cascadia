"use client";

import {
  CartesianGrid,
  LabelList,
  Label,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";

import type { ParetoPoint } from "@/lib/api";
import { roundPct } from "@/lib/format";

export interface CurvePoint {
  cost: number;
  quality: number;
}

// Higher escalation rate ≈ higher per-request cost (more expensive-tier calls).
// We chart that as the cost axis. Mean judge score is the quality axis.
//
// `frontier` (optional) draws the fitted Pareto curve as a dashed line;
// `projected` (optional) drops a distinct marker at the slider's current
// quality→cost projection. Both are used by the navigable-frontier slider.
export function ParetoChart({
  points,
  frontier,
  projected,
}: {
  points: ParetoPoint[];
  frontier?: CurvePoint[];
  projected?: CurvePoint | null;
}) {
  const data = points.map((p) => ({
    cluster: p.cluster_id,
    cost: p.escalation_rate,
    quality: p.mean_quality,
    n: p.sample_size,
  }));
  const frontierData = (frontier ?? []).map((p) => ({ cost: p.cost, quality: p.quality, n: 1 }));
  const projectedData = projected ? [{ cost: projected.cost, quality: projected.quality, n: 1 }] : [];
  // WCAG 1.1.1: build an accessible-name summary of the chart's data so
  // screen-reader users hear meaningful content instead of a stream of
  // anonymous percentage strings emitted by the Recharts SVG. Full numeric
  // data is also rendered as a visually-hidden <table> fallback below the
  // chart so assistive-tech users can navigate the underlying numbers.
  const summary =
    data.length === 0
      ? "No Pareto data in the current window."
      : `Pareto frontier scatter chart with ${data.length} cluster${
          data.length === 1 ? "" : "s"
        }. X axis: escalation rate as cost proxy. Y axis: mean judge score as quality. Dot size: sample count.`;
  return (
    <div className="w-full h-[360px] border border-border rounded-md bg-bg-surface p-4">
      <div
        role="img"
        aria-label={summary}
        className="w-full h-full"
      >
      {/* The recharts SVG is hidden from assistive tech: the role="img"
          label above and the sr-only <table> below carry the data. Without
          this, screen readers drill into nested unnamed <g role="img"> nodes
          and a stream of bare axis-tick numbers. */}
      <div aria-hidden="true" className="w-full h-full">
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 12, right: 32, bottom: 24, left: 12 }}>
          <CartesianGrid stroke="#1F2632" strokeDasharray="3 3" />
          <XAxis
            type="number"
            dataKey="cost"
            domain={[0, 1]}
            tickFormatter={(v) => roundPct(v)}
            stroke="#9098A8"
          >
            <Label
              value="Escalation rate (cost proxy)"
              offset={-10}
              position="insideBottom"
              fill="#9098A8"
            />
          </XAxis>
          <YAxis
            type="number"
            dataKey="quality"
            domain={[0, 1]}
            tickFormatter={(v) => roundPct(v)}
            stroke="#9098A8"
          >
            <Label
              value="Mean judge score (quality)"
              angle={-90}
              position="insideLeft"
              fill="#9098A8"
              style={{ textAnchor: "middle" }}
            />
          </YAxis>
          <ZAxis type="number" dataKey="n" range={[60, 400]} />
          <Tooltip
            cursor={{ stroke: "#5AE3D6", strokeDasharray: "3 3" }}
            contentStyle={{
              background: "#11151C",
              border: "1px solid #2A3344",
              color: "#E6E8EC",
              fontFamily: "JetBrains Mono",
              fontSize: 12,
            }}
            content={({ active, payload }) => {
              if (!active || !payload?.length) return null;
              const p = payload[0].payload as {
                cluster: string;
                cost: number;
                quality: number;
                n: number;
              };
              return (
                <div
                  style={{
                    background: "#11151C",
                    border: "1px solid #2A3344",
                    color: "#E6E8EC",
                    fontFamily: "JetBrains Mono",
                    fontSize: 12,
                    padding: "8px 10px",
                    borderRadius: 4,
                  }}
                >
                  <div style={{ color: "#5AE3D6", marginBottom: 2 }}>
                    {p.cluster}
                  </div>
                  <div>quality: {roundPct(p.quality)}</div>
                  <div>escalation: {roundPct(p.cost)}</div>
                  <div style={{ color: "#9098A8" }}>n = {p.n}</div>
                </div>
              );
            }}
          />
          {/* Fitted Pareto frontier (dashed line, no dots) — rendered first so
              the cluster dots sit on top of it. */}
          {frontierData.length > 1 && (
            <Scatter
              data={frontierData}
              line={{ stroke: "#5AE3D6", strokeWidth: 1, strokeDasharray: "5 4" }}
              lineType="joint"
              fill="none"
              shape={() => <g />}
              isAnimationActive={false}
            />
          )}
          <Scatter data={data} fill="#5AE3D6">
            <LabelList
              dataKey="cluster"
              position="top"
              offset={12}
              style={{
                fill: "#E6E8EC",
                fontFamily: "JetBrains Mono",
                fontSize: 11,
                paintOrder: "stroke",
                stroke: "#11151C",
                strokeWidth: 3,
                strokeLinecap: "round",
                strokeLinejoin: "round",
              }}
            />
          </Scatter>
          {/* Slider's current quality→cost projection (amber diamond). */}
          {projectedData.length > 0 && (
            <Scatter
              data={projectedData}
              fill="#F5A623"
              shape="diamond"
              isAnimationActive={false}
            />
          )}
        </ScatterChart>
      </ResponsiveContainer>
      </div>
      </div>
      {/* Screen-reader-only table: full numeric data behind the chart for AT
          users + a forced-colors / no-SVG fallback. The `sr-only` lives on a
          wrapping <div>, not the <table>: a <table> ignores sr-only's
          `width:1px` (table layout sizes to content), so it stays full-width
          and, being position:absolute, overflows the page on narrow
          viewports. A <div> clips it cleanly. */}
      <div className="sr-only">
      <table>
        <caption>Pareto frontier — per-cluster operating points.</caption>
        <thead>
          <tr>
            <th scope="col">Cluster</th>
            <th scope="col">Escalation rate</th>
            <th scope="col">Mean quality</th>
            <th scope="col">Sample size</th>
          </tr>
        </thead>
        <tbody>
          {data.map((d) => (
            <tr key={d.cluster}>
              <td>{d.cluster}</td>
              <td>{roundPct(d.cost)}</td>
              <td>{roundPct(d.quality)}</td>
              <td>{d.n}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}
