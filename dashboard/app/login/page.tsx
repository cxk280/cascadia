import { Suspense } from "react";
import type { Metadata } from "next";

import { AuthForm } from "@/components/AuthForm";
import { AuthScreen } from "@/components/AuthScreen";

export const metadata: Metadata = {
  title: "Sign in",
};

export default function LoginPage() {
  return (
    <AuthScreen title="Sign in" subtitle="Access your Cascadia operator dashboard.">
      {/* AuthForm reads ?next via useSearchParams, which Next requires be
          wrapped in a Suspense boundary. */}
      <Suspense fallback={null}>
        <AuthForm mode="login" />
      </Suspense>
    </AuthScreen>
  );
}
