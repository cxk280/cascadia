"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Shell } from "@/components/Shell";
import { calibrate, type CalibrateProgress } from "@/lib/calibrate-client";

const REVIEWER_COOKIE = "cascadia_reviewer_id";

function readReviewer(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/(?:^|;\s*)cascadia_reviewer_id=([^;]+)/);
  if (!match) return null;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    // A manually-set/corrupted cookie with a malformed percent-sequence
    // throws URIError; don't let that break the page render.
    return null;
  }
}

function writeReviewer(id: string) {
  document.cookie = `${REVIEWER_COOKIE}=${encodeURIComponent(id)}; path=/; max-age=${60 * 60 * 24 * 30}`;
}

function clearReviewer() {
  document.cookie = `${REVIEWER_COOKIE}=; path=/; max-age=0`;
}

export default function CalibrateLanding() {
  const [reviewerId, setReviewerId] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [idInput, setIdInput] = useState("");
  const [progress, setProgress] = useState<CalibrateProgress | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setReviewerId(readReviewer());
  }, []);

  useEffect(() => {
    if (!reviewerId) return;
    setError(null);
    calibrate
      .progress(reviewerId)
      .then(setProgress)
      .catch((e) => setError(String(e)));
  }, [reviewerId]);

  async function handleOnboard(e: React.FormEvent) {
    e.preventDefault();
    if (!idInput.trim() || !displayName.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const cleanId = idInput.trim().toLowerCase().replace(/[^a-z0-9_-]/g, "-");
      if (!/[a-z0-9]/.test(cleanId)) {
        setError("reviewer_id must contain at least one letter or digit");
        setBusy(false);
        return;
      }
      const result = await calibrate.onboard(cleanId, displayName.trim());
      if (result.already_existed) {
        // The API treats re-onboarding as idempotent — return 200 with the
        // existing reviewer row. But silently signing the user in as
        // someone else is the worst outcome: Bob types "chris" by accident
        // and starts labeling on Chris's behalf. Surface the collision.
        const proceed = confirm(
          `A reviewer with id "${cleanId}" already exists (display name: "${result.display_name}"). ` +
            `If that's you, click OK to sign back in. If you meant to create a new account, ` +
            `click Cancel and choose a different reviewer id.`,
        );
        if (!proceed) {
          setBusy(false);
          return;
        }
      }
      writeReviewer(cleanId);
      setReviewerId(cleanId);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  function handleSwitch() {
    clearReviewer();
    setReviewerId(null);
    setProgress(null);
  }

  return (
    <Shell active="/calibrate">
      <h1 className="text-2xl font-semibold tracking-tight">Calibration labeling</h1>
      <p className="text-fg-muted text-sm mt-1">
        Help build the Phase-5 human-rated calibration set. Each pair takes ~30
        seconds. <Link href="/calibrate/rubric" className="text-accent hover:underline">Read the rubric first →</Link>
      </p>

      {!reviewerId ? (
        <form
          onSubmit={handleOnboard}
          className="mt-8 border border-border rounded-md bg-bg-surface p-6 max-w-lg space-y-4"
        >
          <div className="text-sm font-medium">Identify yourself</div>
          <p className="text-xs text-fg-muted">
            Pick a short stable handle (your first name is fine) — we use it to
            compute inter-rater agreement. No password. Stored only in your
            browser cookie and the Cascadia DB.
          </p>
          <label className="block">
            <span className="text-xs text-fg-muted">reviewer_id</span>
            <input
              type="text"
              name="reviewer_id"
              autoComplete="username"
              value={idInput}
              onChange={(e) => {
                setIdInput(e.target.value);
                if (error) setError(null);
              }}
              placeholder="chris"
              autoFocus
              aria-invalid={!!error && error.startsWith("reviewer_id must")}
              className={`mt-1 w-full bg-bg-raised border rounded px-3 py-1.5 font-mono text-sm ${
                error && error.startsWith("reviewer_id must")
                  ? "border-accent-danger"
                  : "border-border"
              }`}
            />
            {error && error.startsWith("reviewer_id must") && (
              <div className="mt-1 text-xs text-accent-danger">{error}</div>
            )}
          </label>
          <label className="block">
            <span className="text-xs text-fg-muted">display name</span>
            <input
              type="text"
              name="display_name"
              autoComplete="name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Chris King"
              className="mt-1 w-full bg-bg-raised border border-border rounded px-3 py-1.5 text-sm"
            />
          </label>
          {/* Server-side error (not field validation) — fetch failed, etc. */}
          {error && !error.startsWith("reviewer_id must") && (
            <div className="border border-accent-danger/40 bg-accent-danger/5 text-accent-danger text-sm rounded-md px-3 py-2">
              {error}
            </div>
          )}
          <button
            type="submit"
            disabled={busy || !idInput.trim() || !displayName.trim()}
            className="bg-accent text-bg font-medium px-4 py-1.5 rounded text-sm disabled:opacity-40"
          >
            {busy ? "..." : "Start labeling"}
          </button>
        </form>
      ) : (
        <div className="mt-8 grid grid-cols-1 md:grid-cols-2 gap-4 max-w-3xl">
          <div className="border border-border rounded-md bg-bg-surface p-6">
            <div className="text-xs uppercase tracking-widest text-fg-subtle">
              Logged in as
            </div>
            <div className="mt-1 font-mono text-fg text-lg">{reviewerId}</div>
            <button
              onClick={handleSwitch}
              className="mt-3 text-xs text-fg-muted hover:text-fg underline"
            >
              Switch reviewer
            </button>
          </div>
          <div className="border border-border rounded-md bg-bg-surface p-6">
            <div className="text-xs uppercase tracking-widest text-fg-subtle">
              Your queue
            </div>
            {progress ? (
              <>
                <div className="mt-1 font-mono text-fg text-lg">
                  {progress.n_labeled} labeled · {progress.n_pending} pending
                </div>
                <div className="text-xs text-fg-muted mt-1">
                  attention checks: {progress.n_attention_passed} passed /{" "}
                  {progress.n_attention_failed} failed
                </div>
              </>
            ) : (
              <div className="text-fg-muted text-sm mt-1">loading…</div>
            )}
          </div>
          <div className="md:col-span-2">
            <Link
              href="/calibrate/label"
              className="inline-block bg-accent text-bg font-medium px-5 py-2 rounded"
            >
              {progress && progress.n_pending > 0
                ? `Continue labeling (${progress.n_pending} pairs left) →`
                : progress && progress.n_pending === 0
                  ? "Queue empty — check back after the next sampler run"
                  : "Start labeling →"}
            </Link>
          </div>
        </div>
      )}
    </Shell>
  );
}
