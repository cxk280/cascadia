/// Inline help tooltip for column headers, metric labels, and other places
/// where one extra sentence saves the operator from filing a bogus bug.
///
/// Renders a small `ⓘ` glyph that reveals a tooltip on hover/focus. Uses the
/// same group-hover pattern as ProxyLivePip's LiveTooltip so the styling
/// matches.

"use client";

import * as React from "react";

export function InfoTip({
  label,
  children,
  align = "right",
}: {
  /// What the user is hovering. Renders as the visible text next to the glyph.
  label: React.ReactNode;
  /// Tooltip body. Single sentence is best; supports React nodes for links.
  children: React.ReactNode;
  /// Which side of the glyph the tooltip floats toward.
  align?: "left" | "right";
}) {
  // useId() produces hydration-safe IDs that match across SSR and the
  // client hydration pass. A module-level counter would drift between
  // server and client renders (counter increments per Node process,
  // per-mount on the client), silently breaking the aria-describedby
  // association after hydration.
  const tipId = React.useId();
  // Build an accessible name that names the column / metric this tip is
  // for — without this, AT users navigating by button hear "More info,
  // More info, More info..." with no column context.
  const labelText = typeof label === "string" ? label : "this metric";
  return (
    <span className="relative inline-flex items-center gap-1 group">
      <span>{label}</span>
      <button
        type="button"
        aria-label={`${labelText} — more info`}
        aria-describedby={tipId}
        // WCAG 2.4.7: replace the removed default outline with a visible
        // ring so keyboard users can see where focus is.
        className="inline-flex items-center justify-center w-4 h-4 rounded-full border border-border text-fg-muted text-[10px] font-semibold cursor-help group-hover:bg-bg-raised group-focus-within:bg-bg-raised focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-bg-surface"
      >
        i
      </button>
      <span
        id={tipId}
        role="tooltip"
        className={`absolute top-full ${
          align === "right" ? "right-0" : "left-0"
        } mt-1 w-72 z-30 hidden group-hover:block group-focus-within:block normal-case tracking-normal font-normal`}
      >
        <span className="block border border-border bg-bg-raised text-fg text-xs rounded-md px-3 py-2 leading-relaxed shadow-lg">
          {children}
        </span>
      </span>
    </span>
  );
}
