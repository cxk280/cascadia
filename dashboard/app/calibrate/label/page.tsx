"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Shell } from "@/components/Shell";
import {
  calibrate,
  type CalibrateNextPair,
  type LabelChoice,
} from "@/lib/calibrate-client";

function readReviewer(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/(?:^|;\s*)cascadia_reviewer_id=([^;]+)/);
  if (!match) return null;
  try {
    return decodeURIComponent(match[1]);
  } catch {
    // A malformed percent-sequence in a corrupted cookie throws URIError;
    // don't let that break the label page render.
    return null;
  }
}

const LABELS: Array<{ key: string; choice: LabelChoice; help: string; tone: string }> = [
  { key: "a", choice: "a", help: "Slot A wins", tone: "border-accent text-accent" },
  { key: "b", choice: "b", help: "Slot B wins", tone: "border-accent text-accent" },
  { key: "t", choice: "tie", help: "Tie / both equivalent", tone: "border-fg-muted text-fg" },
  { key: "u", choice: "unknown", help: "Unknown — excluded from dataset", tone: "border-fg-subtle text-fg-muted" },
];

export default function LabelPage() {
  const [reviewerId, setReviewerId] = useState<string | null>(null);
  const [pair, setPair] = useState<CalibrateNextPair | null>(null);
  const [queueEmpty, setQueueEmpty] = useState(false);
  // Labels-so-far counter used to disambiguate "empty queue because typo'd
  // reviewer_id" (n_labeled = 0) from "empty queue because genuinely
  // finished" (n_labeled > 0).
  const [labelsSoFar, setLabelsSoFar] = useState<number | null>(null);
  const [rationale, setRationale] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // WCAG 2.1.4 — single-character shortcuts (`a`/`b`/`t`/`u`) must be
  // deactivatable for AT users who run their own single-key navigation.
  const [shortcutsEnabled, setShortcutsEnabled] = useState(true);
  const startedRef = useRef<number>(Date.now());

  useEffect(() => {
    setReviewerId(readReviewer());
  }, []);

  const loadNext = useCallback(async () => {
    if (!reviewerId) return;
    setError(null);
    setRationale("");
    setBusy(true);
    try {
      const res = await calibrate.next(reviewerId);
      if (res.pair == null) {
        setPair(null);
        setQueueEmpty(true);
        // Pull progress so the empty-queue screen can distinguish
        // "you've never labeled anything (probably a typo'd reviewer_id)"
        // from "you're caught up".
        try {
          const prog = await calibrate.progress(reviewerId);
          setLabelsSoFar(prog.n_labeled);
        } catch {
          setLabelsSoFar(null);
        }
      } else {
        setPair(res.pair);
        setQueueEmpty(false);
        startedRef.current = Date.now();
      }
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }, [reviewerId]);

  useEffect(() => {
    void loadNext();
  }, [loadNext]);

  const submit = useCallback(
    async (choice: LabelChoice) => {
      if (!reviewerId || !pair || busy) return;
      const elapsed = Date.now() - startedRef.current;
      setBusy(true);
      setError(null);
      try {
        await calibrate.submit({
          pair_id: pair.pair_id,
          reviewer_id: reviewerId,
          raw_label: choice,
          rationale: rationale.trim() || undefined,
          time_ms: elapsed,
        });
        await loadNext();
      } catch (err) {
        setError(String(err));
        setBusy(false);
      }
    },
    [reviewerId, pair, rationale, busy, loadNext],
  );

  // Keyboard shortcuts. A / B / T / U with Cmd-Enter as alt submit on the
  // currently-focused button. Wires onto window so they fire even when the
  // rationale textarea has focus — Escape gives the user a way to type into
  // rationale without accidentally submitting.
  useEffect(() => {
    if (!shortcutsEnabled) return;
    function onKey(e: KeyboardEvent) {
      if (!pair) return;
      const target = e.target as HTMLElement | null;
      if (target?.tagName === "TEXTAREA" || target?.tagName === "INPUT") {
        // Allow Esc to blur rationale and re-enable shortcuts.
        if (e.key === "Escape") (target as HTMLElement).blur();
        return;
      }
      const map = LABELS.find((l) => l.key === e.key.toLowerCase());
      if (map) {
        e.preventDefault();
        void submit(map.choice);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [pair, submit, shortcutsEnabled]);

  const progressLabel = useMemo(() => {
    if (!pair) return "";
    return `pair ${pair.queue_position} of ${pair.queue_size}`;
  }, [pair]);

  if (!reviewerId) {
    return (
      <Shell active="/calibrate">
        <h1 className="text-2xl font-semibold tracking-tight">Label pair</h1>
        <div className="mt-6 border border-border rounded-md bg-bg-surface px-4 py-4">
          <p className="text-fg-muted text-sm">
            You need to onboard before labeling pairs. We&apos;ll bring you
            right back here after.
          </p>
          <Link
            href="/calibrate?redirect=label"
            className="mt-3 inline-block text-sm border border-accent/40 bg-accent/5 text-accent rounded-md px-3 py-1.5 hover:bg-accent/10"
          >
            Onboard now →
          </Link>
          <p className="mt-3 text-xs text-fg-muted">
            Already onboarded on another device? Re-enter the same{" "}
            <code className="font-mono">reviewer_id</code> on the onboarding
            page to resume your queue.
          </p>
        </div>
      </Shell>
    );
  }

  return (
    <Shell active="/calibrate">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">Label pair</h1>
        <div className="text-xs text-fg-muted font-mono">
          {progressLabel} · reviewer={reviewerId} ·{" "}
          <Link href="/calibrate" className="text-accent hover:underline">back</Link>
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="mt-4 border border-accent-danger/40 bg-accent-danger/5 text-accent-danger text-sm rounded-md px-4 py-3"
        >
          {error}
        </div>
      )}

      {/* Always-mounted status region. WCAG 4.1.3 — keep this in the DOM
          across all states so AT users hear announcements for submission,
          queue-empty, and idle without the live-region itself remounting. */}
      <div role="status" aria-live="polite" className="sr-only">
        {busy
          ? "Submitting label, loading next pair."
          : queueEmpty
            ? "Queue empty. No more pairs to label."
            : ""}
      </div>

      {queueEmpty && (
        <div className="mt-8 border border-border rounded-md bg-bg-surface px-6 py-10 text-center">
          {labelsSoFar === 0 ? (
            <>
              <div className="text-accent-warn text-sm">
                No pairs found AND no labels recorded for{" "}
                <code className="font-mono">{reviewerId}</code>.
              </div>
              <div className="text-xs text-fg-subtle mt-2">
                If this isn&apos;t the reviewer id you onboarded with, you
                may have a typo — go to{" "}
                <Link href="/calibrate" className="text-accent hover:underline">
                  /calibrate
                </Link>{" "}
                to switch reviewers. Otherwise the calibration queue is empty;
                run the sampler to pull a batch.
              </div>
            </>
          ) : (
            <>
              <div className="text-fg-muted text-sm">
                Queue empty — no more pairs to label.{" "}
                {labelsSoFar != null && (
                  <span>You&apos;ve labeled {labelsSoFar} pair{labelsSoFar === 1 ? "" : "s"} this session.</span>
                )}
              </div>
              <div className="text-xs text-fg-subtle mt-2">
                Run the sampler to pull another batch, or check back later.
              </div>
            </>
          )}
        </div>
      )}

      {pair && (
        <>
          <div className="mt-4 text-xs text-fg-subtle">
            Tip: press <kbd className="px-1 border border-border rounded font-mono">A</kbd>{" "}
            <kbd className="px-1 border border-border rounded font-mono">B</kbd>{" "}
            <kbd className="px-1 border border-border rounded font-mono">T</kbd>{" "}
            <kbd className="px-1 border border-border rounded font-mono">U</kbd>{" "}
            to label without clicking. Press{" "}
            <kbd className="px-1 border border-border rounded font-mono">Esc</kbd>{" "}
            inside the rationale field to release keyboard focus.
          </div>
          <div className="mt-6 border border-border rounded-md bg-bg-surface p-5">
            <div className="text-[10px] uppercase tracking-widest text-fg-subtle">prompt</div>
            <pre className="mt-2 text-sm whitespace-pre-wrap font-mono text-fg">
              {pair.prompt}
            </pre>
          </div>

          <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="border border-border rounded-md bg-bg-surface p-5">
              <div className="text-[10px] uppercase tracking-widest text-accent">slot A</div>
              <pre className="mt-2 text-sm whitespace-pre-wrap font-mono text-fg">
                {pair.display_a}
              </pre>
            </div>
            <div className="border border-border rounded-md bg-bg-surface p-5">
              <div className="text-[10px] uppercase tracking-widest text-accent">slot B</div>
              <pre className="mt-2 text-sm whitespace-pre-wrap font-mono text-fg">
                {pair.display_b}
              </pre>
            </div>
          </div>

          <div
            className="mt-5 flex flex-wrap gap-3"
            role="group"
            aria-label="Label this pair"
          >
            {LABELS.map((l) => (
              <button
                key={l.choice}
                disabled={busy}
                onClick={() => submit(l.choice)}
                // WCAG 2.1.4 / 4.1.2 — declare the keyboard shortcut to AT
                // so screen-reader users know the global `a`/`b`/`t`/`u`
                // bindings exist. The bracketed `[A]` glyph is visual-only.
                aria-keyshortcuts={l.key}
                aria-label={`${l.help}. Keyboard shortcut: ${l.key.toUpperCase()}.`}
                className={`border px-4 py-2 rounded-md text-sm font-medium hover:bg-bg-raised disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1 focus-visible:ring-offset-bg-surface ${l.tone}`}
              >
                <span className="font-mono mr-2 opacity-70" aria-hidden="true">
                  [{l.key.toUpperCase()}]
                </span>
                {l.help}
              </button>
            ))}
          </div>

          <div className="mt-4">
            <label htmlFor="rationale" className="block text-xs text-fg-muted mb-1">
              optional rationale — flag rubric ambiguity here
            </label>
            <textarea
              id="rationale"
              value={rationale}
              onChange={(e) => setRationale(e.target.value)}
              rows={2}
              placeholder="Press Esc when done to re-enable keyboard shortcuts."
              className="w-full bg-bg-raised border border-border rounded px-3 py-2 text-sm font-mono"
            />
          </div>

          {/* WCAG 2.1.4 — keyboard shortcut deactivation. AT users running
              single-key navigation can disable the global A/B/T/U handlers
              here; the buttons themselves remain operable via Enter/Space. */}
          <div className="mt-4 text-xs text-fg-subtle flex items-center gap-2">
            <input
              id="shortcuts-toggle"
              type="checkbox"
              checked={shortcutsEnabled}
              onChange={(e) => setShortcutsEnabled(e.target.checked)}
              className="cursor-pointer"
            />
            <label htmlFor="shortcuts-toggle" className="cursor-pointer">
              Enable keyboard shortcuts (A / B / T / U). Uncheck if you use
              single-key screen-reader navigation.
            </label>
          </div>

          <div className="mt-4 text-xs text-fg-subtle font-mono">
            cluster={pair.cluster_id ?? "—"} · round={pair.selection_round} · reason={pair.selection_reason}
          </div>
        </>
      )}
    </Shell>
  );
}
