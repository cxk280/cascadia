import { api } from "@/lib/api";
import { ProxyLivePip } from "./ProxyLivePip";

/// Server wrapper that runs the first probe at render time and passes the
/// result to the client component as initial state. Eliminates the 1-2s
/// "blank corner" gap Reggie hated on first page load.
export async function ProxyLivePipServer() {
  let initial: { reachable: boolean | null; shuttingDown: boolean } = {
    reachable: null,
    shuttingDown: false,
  };
  try {
    const body = await api.proxyReachable();
    const shutting =
      body.readyz?.status === "shutting_down" ||
      body.readyz?.failed_checks?.includes("shutting_down");
    // SSR seeds only steady states (live OR down). A "draining" snapshot
    // from SSR can go stale within seconds (proxy may have fully exited
    // by the time the browser hydrates), which would freeze the pip in a
    // wrong state until the first client poll. Letting the client resolve
    // the transient costs ~2s of no-pip but never lies.
    if (!shutting) {
      initial = { reachable: body.reachable === true, shuttingDown: false };
    }
  } catch {
    // fall through with null
  }
  return <ProxyLivePip initial={initial} />;
}
