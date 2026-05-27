// Browser-side calibration client. Calls the Next.js Route Handlers under
// /api/calibrate/* which proxy to the FastAPI dashboard-api. We never
// talk to the Python service directly from the browser — that way the
// dashboard-api can stay private (no public CORS allowlist needed) and
// the labeling tool works behind a single Next.js origin.

export type LabelChoice = "a" | "b" | "tie" | "unknown";

export interface CalibrateNextPair {
  pair_id: string;
  prompt: string;
  display_a: string;
  display_b: string;
  cluster_id: string | null;
  selection_round: number;
  selection_reason: string;
  queue_position: number;
  queue_size: number;
}

export interface CalibrateNextResponse {
  pair: CalibrateNextPair | null;
  queue_size: number;
}

export interface CalibrateProgress {
  reviewer_id: string;
  n_labeled: number;
  n_pending: number;
  n_attention_passed: number;
  n_attention_failed: number;
}

export interface CalibrateRubric {
  version: string;
  markdown: string;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`GET ${path} → HTTP ${res.status}: ${detail}`);
  }
  return (await res.json()) as T;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`POST ${path} → HTTP ${res.status}: ${detail}`);
  }
  return (await res.json()) as T;
}

export const calibrate = {
  rubric: () => getJson<CalibrateRubric>("/api/calibrate/rubric"),
  progress: (reviewerId: string) =>
    getJson<CalibrateProgress>(
      `/api/calibrate/progress?reviewer_id=${encodeURIComponent(reviewerId)}`,
    ),
  next: (reviewerId: string) =>
    getJson<CalibrateNextResponse>(
      `/api/calibrate/next?reviewer_id=${encodeURIComponent(reviewerId)}`,
    ),
  onboard: (reviewerId: string, displayName: string) =>
    postJson<{
      reviewer_id: string;
      display_name: string;
      onboarded_at: string;
      already_existed: boolean;
    }>("/api/calibrate/reviewers", {
      reviewer_id: reviewerId,
      display_name: displayName,
    }),
  submit: (req: {
    pair_id: string;
    reviewer_id: string;
    raw_label: LabelChoice;
    rationale?: string;
    time_ms?: number;
  }) =>
    postJson<{
      pair_id: string;
      reviewer_id: string;
      label_id: string;
      accepted: boolean;
    }>("/api/calibrate/labels", req),
};
