"use client";

import { useEffect, useId, useState } from "react";

function LiveTooltip({ tipId }: { tipId: string }) {
  return (
    <div
      id={tipId}
      role="tooltip"
      className="absolute right-0 top-full mt-2 w-72 z-20 hidden group-hover:block group-focus-within:block"
    >
      <div className="border border-border bg-bg-raised text-fg-muted text-xs rounded-md px-3 py-2 leading-relaxed shadow-lg">
        <div className="text-fg text-[11px] uppercase tracking-wider mb-1">
          Proxy live
        </div>
        Header status polls the proxy every 2 seconds. Metrics on the
        dashboard pages are cached and revalidate every 10 seconds — reload
        to force a refresh.
      </div>
    </div>
  );
}

interface PipState {
  reachable: boolean | null;
  shuttingDown: boolean;
}

/// Tiny always-visible status pip for the Shell header. Initial state may be
/// provided via SSR so the pip renders correctly on first paint without the
/// 1-2s flash of nothing while the first client-side probe completes.
/// Then polls every 2s.
export function ProxyLivePip({
  initial = { reachable: null, shuttingDown: false },
}: {
  initial?: PipState;
}) {
  const [pip, setPip] = useState<PipState>(initial);

  useEffect(() => {
    let cancelled = false;
    async function probe() {
      try {
        const res = await fetch("/api/proxy-reachable", { cache: "no-store" });
        if (!res.ok || cancelled) return;
        const body = await res.json();
        if (cancelled) return;
        setPip({
          reachable: body.reachable === true,
          shuttingDown:
            body.readyz?.status === "shutting_down" ||
            body.readyz?.failed_checks?.includes?.("shutting_down"),
        });
      } catch {
        // dashboard-api unreachable — leave the pip in its last state.
      }
    }
    probe();
    const t = setInterval(probe, 2000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  const tipId = useId();

  // A single persistent live region wraps every state, so a screen reader
  // hears live → down → draining transitions announced (WCAG 4.1.3). The
  // three states swap content inside it rather than mounting separate
  // role="status" nodes (which announce inconsistently across SR/browser
  // pairs).
  let inner: React.ReactNode = null;
  if (pip.shuttingDown) {
    inner = (
      <span className="inline-flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-accent-warn">
        <span
          aria-hidden="true"
          className="inline-block h-1.5 w-1.5 rounded-full bg-accent-warn animate-pulse"
        />
        draining
        <span className="sr-only"> — proxy graceful shutdown in progress</span>
      </span>
    );
  } else if (pip.reachable === false) {
    inner = (
      <span className="inline-flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-accent-danger">
        <span
          aria-hidden="true"
          className="inline-block h-1.5 w-1.5 rounded-full bg-accent-danger"
        />
        proxy down
        <span className="sr-only"> — proxy unreachable</span>
      </span>
    );
  } else if (pip.reachable === true) {
    inner = (
      <span className="group relative inline-flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-accent">
        <button
          type="button"
          aria-label="Proxy live — more info"
          aria-describedby={tipId}
          className="inline-flex items-center gap-1.5 cursor-help focus:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-bg-surface rounded-sm"
        >
          <span
            aria-hidden="true"
            className="inline-block h-1.5 w-1.5 rounded-full bg-accent"
          />
          proxy live
        </button>
        <LiveTooltip tipId={tipId} />
      </span>
    );
  }
  // reachable === null (no probe data yet) renders an empty but present live
  // region, so the first real status still announces.
  return (
    <span role="status" aria-live="polite" aria-atomic="true">
      {inner}
    </span>
  );
}
