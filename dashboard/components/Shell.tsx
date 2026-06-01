import Link from "next/link";
import { ProxyLivePip } from "./ProxyLivePip";
import { ProxyReachabilityBanner } from "./ProxyReachabilityBanner";
import { UserMenu } from "./UserMenu";

// Calibration labeling (/calibrate, /calibrate/label) is intentionally NOT in
// the operator nav. It's a periodic methodology activity (establishing the
// judge ensemble's agreement with humans), not a daily-driver feature — the
// operator consumes the calibrated judge, they don't hand-label pairs. The
// routes still work by direct URL; when roles land they should be gated to
// admin/reviewer. The /calibrate/rubric page stays public (methodology
// contract). See PLAN.md §9 (2026-06-01).
const NAV: Array<{ label: string; href: string; section: string }> = [
  { section: "OPERATIONS", label: "Overview", href: "/overview" },
  { section: "OPERATIONS", label: "Pareto", href: "/pareto" },
  { section: "OPERATIONS", label: "Clusters", href: "/clusters" },
  { section: "OPERATIONS", label: "Recent activity", href: "/activity" },
  { section: "META", label: "Health", href: "/health" },
];

/// `Shell` is the dashboard's chrome. It is a synchronous component so it can
/// be rendered from both server pages and client pages (Next.js' calibrate
/// flow needs the latter). Pages that want the SSR-seeded proxy-live pip pass
/// it in via `headerSlot`; client pages get a client-only fallback that does
/// the first probe in `useEffect` (~500ms gap on first paint, acceptable).
export function Shell({
  children,
  active,
  headerSlot,
}: {
  children: React.ReactNode;
  active: string;
  headerSlot?: React.ReactNode;
}) {
  const grouped = NAV.reduce<Record<string, typeof NAV>>((acc, item) => {
    (acc[item.section] ||= []).push(item);
    return acc;
  }, {});
  return (
    <div className="min-h-screen flex flex-col">
      {/* WCAG 2.4.1 — skip-link lets keyboard / screen-reader users bypass
          the 7-item sidebar nav on every page load. Visually hidden until
          focused. */}
      <a
        href="#main-content"
        className="sr-only focus-visible:not-sr-only focus-visible:fixed focus-visible:top-2 focus-visible:left-2 focus-visible:z-50 focus-visible:px-3 focus-visible:py-2 focus-visible:bg-bg-raised focus-visible:text-fg focus-visible:border focus-visible:border-accent focus-visible:rounded"
      >
        Skip to main content
      </a>
      <header className="h-14 border-b border-border bg-bg-surface flex items-center px-6 justify-between">
        <div className="flex items-center gap-8">
          <span className="font-mono text-fg font-semibold tracking-tight">Cascadia</span>
          <span className="text-xs uppercase tracking-wider text-fg-muted">operator dashboard</span>
        </div>
        <div className="flex items-center gap-4">
          {headerSlot ?? <ProxyLivePip />}
          <UserMenu />
        </div>
      </header>
      <div className="flex flex-col md:flex-row flex-1 min-h-0">
        {/* Desktop sidebar (md+). Hidden on mobile — a fixed 224px sidebar
            crushes main content to ~150px on a phone, so mobile gets the
            horizontal nav strip below instead. */}
        <nav
          aria-label="Dashboard navigation"
          className="hidden md:block md:w-56 shrink-0 border-r border-border bg-bg-surface px-3 py-6 text-sm"
        >
          {Object.entries(grouped).map(([section, items]) => (
            <div key={section} className="mb-6">
              <div className="text-[10px] tracking-widest uppercase text-fg-muted mb-2 px-2">
                {section}
              </div>
              <ul className="space-y-0.5">
                {items.map((item) => {
                  const isActive = item.href === active;
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        className={`block px-2 py-1.5 rounded ${
                          isActive
                            ? "bg-bg-raised text-fg border-l-2 border-accent"
                            : "text-fg-muted hover:text-fg hover:bg-bg-raised/60"
                        }`}
                      >
                        {item.label}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>
        {/* Mobile nav — horizontal, scrollable strip across the top. Sections
            are flattened to keep it to a single compact row. */}
        <nav
          aria-label="Dashboard navigation"
          className="md:hidden border-b border-border bg-bg-surface overflow-x-auto"
        >
          <ul className="flex gap-1 px-3 py-2 whitespace-nowrap text-sm">
            {NAV.map((item) => {
              const isActive = item.href === active;
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    className={`block px-3 py-2 rounded ${
                      isActive
                        ? "bg-bg-raised text-fg border-b-2 border-accent"
                        : "text-fg-muted hover:text-fg"
                    }`}
                  >
                    {item.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
        <main
          id="main-content"
          tabIndex={-1}
          className="flex-1 min-w-0 min-h-0 overflow-auto p-4 md:p-6"
        >
          <ProxyReachabilityBanner />
          {children}
        </main>
      </div>
    </div>
  );
}
