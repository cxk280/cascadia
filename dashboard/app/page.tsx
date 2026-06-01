import { redirect } from "next/navigation";

// The operator overview lives at /overview. The root path redirects there so
// the dashboard has one canonical home. (Auth middleware runs first: an
// unauthenticated request to / is sent to /login before this redirect.)
export const dynamic = "force-dynamic";

export default function RootPage() {
  redirect("/overview");
}
