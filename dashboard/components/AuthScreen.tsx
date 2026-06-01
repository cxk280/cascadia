import Link from "next/link";

// Presentational chrome for the pre-auth pages (login / signup): a centered
// card on the dark canvas with the Cascadia wordmark, matching the dashboard's
// design tokens. No sidebar / Shell — these render before a session exists.
export function AuthScreen({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <main className="min-h-screen flex flex-col items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <Link href="/" className="inline-flex items-center gap-2">
            <span className="font-mono text-fg font-semibold tracking-tight text-lg">
              Cascadia
            </span>
          </Link>
          <div className="text-xs uppercase tracking-wider text-fg-muted mt-1">
            operator dashboard
          </div>
        </div>

        <div className="border border-border rounded-lg bg-bg-surface p-6 shadow-xl shadow-black/20">
          <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
          <p className="text-sm text-fg-muted mt-1 mb-5">{subtitle}</p>
          {children}
        </div>
      </div>
    </main>
  );
}
