"use client";

import { useEffect, useState } from "react";

import { MarkdownRubric } from "@/components/MarkdownRubric";
import { Shell } from "@/components/Shell";
import { calibrate, type CalibrateRubric } from "@/lib/calibrate-client";

export default function RubricPage() {
  const [rubric, setRubric] = useState<CalibrateRubric | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    calibrate
      .rubric()
      .then(setRubric)
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <Shell active="/calibrate">
      <h1 className="text-2xl font-semibold tracking-tight">Calibration rubric</h1>
      <p className="text-fg-muted text-sm mt-1">
        The contract for reviewers. Versioned alongside labels in the DB so a
        future audit can answer &ldquo;which rubric were they using?&rdquo;
      </p>
      {!rubric && !error && (
        <div className="mt-6 text-fg-muted text-sm">
          Loading rubric…
        </div>
      )}
      {error && (
        <div
          role="alert"
          className="mt-4 border border-accent-danger/40 bg-accent-danger/5 text-accent-danger text-sm rounded-md px-4 py-3"
        >
          {error}
        </div>
      )}
      {rubric && (
        <div className="mt-6 max-w-3xl">
          <div className="text-xs text-fg-subtle uppercase tracking-widest mb-3">
            version {rubric.version}
          </div>
          <div className="border border-border rounded-md bg-bg-surface p-6">
            <MarkdownRubric markdown={rubric.markdown} />
          </div>
        </div>
      )}
    </Shell>
  );
}
