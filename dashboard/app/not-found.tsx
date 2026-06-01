import Link from "next/link";

import { AuthScreen } from "@/components/AuthScreen";

// A 404 must not render the operator Shell (sidebar + header): a logged-out
// visitor can hit a bad URL, and the nav links lead behind the session gate.
// Use the chrome-free centered card instead.
export default function NotFound() {
  return (
    <AuthScreen title="404" subtitle="That page doesn't exist.">
      <Link
        href="/overview"
        className="text-accent text-sm hover:underline"
      >
        Back to overview →
      </Link>
    </AuthScreen>
  );
}
