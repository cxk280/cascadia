import { Suspense } from "react";
import type { Metadata } from "next";

import { AuthScreen } from "@/components/AuthScreen";
import { VerifyClient } from "@/components/VerifyClient";

export const metadata: Metadata = {
  title: "Confirm your account",
};

export default function VerifyPage() {
  return (
    <AuthScreen
      title="Confirming your account"
      subtitle="One moment while we confirm your email."
    >
      {/* VerifyClient reads ?token via useSearchParams — needs a Suspense boundary. */}
      <Suspense fallback={null}>
        <VerifyClient />
      </Suspense>
    </AuthScreen>
  );
}
