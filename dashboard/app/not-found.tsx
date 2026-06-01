import Link from "next/link";

import { Shell } from "@/components/Shell";

export default function NotFound() {
  return (
    <Shell active="">
      <h1 className="text-2xl font-semibold tracking-tight">404</h1>
      <p className="text-fg-muted text-sm mt-2">
        That page doesn&apos;t exist.{" "}
        <Link href="/overview" className="text-accent hover:underline">
          Back to overview →
        </Link>
      </p>
    </Shell>
  );
}
