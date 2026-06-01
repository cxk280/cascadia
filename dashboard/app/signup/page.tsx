import { Suspense } from "react";
import type { Metadata } from "next";

import { AuthForm } from "@/components/AuthForm";
import { AuthScreen } from "@/components/AuthScreen";

export const metadata: Metadata = {
  title: "Create account",
};

export default function SignupPage() {
  return (
    <AuthScreen
      title="Create your account"
      subtitle="Set up access to the Cascadia operator dashboard."
    >
      <Suspense fallback={null}>
        <AuthForm mode="signup" />
      </Suspense>
    </AuthScreen>
  );
}
