// Shared display formatters for metric values.
//
// Centralizes the `null → "—"` guard and the exact percent/decimal formatting
// that the overview, clusters, health, and activity pages each render, so a
// rate or score is formatted identically everywhere. Pure functions, no I/O —
// safe in both server and client components.

/** A fraction (0–1) as a percentage string: `0.123 → "12.3%"`. `null`/
 *  `undefined` render as an em dash. `digits` sets decimal places. */
export function pct(value: number | null | undefined, digits = 1): string {
  if (value == null) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

/** A number to fixed decimals: `0.7 → "0.70"`. `null`/`undefined` → em dash. */
export function num(value: number | null | undefined, digits = 2): string {
  if (value == null) return "—";
  return value.toFixed(digits);
}

/** A millisecond latency: `12.3 → "12.3 ms"`. `null`/`undefined` → em dash. */
export function ms(value: number | null | undefined): string {
  if (value == null) return "—";
  return `${value.toFixed(1)} ms`;
}
