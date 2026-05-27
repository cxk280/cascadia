import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Cascadia — Operator Dashboard",
    template: "%s · Cascadia",
  },
  description:
    "Per-cluster cascade routing with a closed feedback loop from prod traffic to routing policy.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="font-sans antialiased bg-bg text-fg">{children}</body>
    </html>
  );
}
