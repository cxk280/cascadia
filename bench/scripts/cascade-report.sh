#!/usr/bin/env bash
# Print a Phase-2 cascade summary from the events table.
# Usage:
#   $ bench/scripts/cascade-report.sh                          # uses CASCADIA_DATABASE_URL
#   $ bench/scripts/cascade-report.sh "postgres://..."          # explicit URL

set -euo pipefail

PG_URL="${1:-${CASCADIA_DATABASE_URL:-postgres://cascadia:cascadia@localhost:5432/cascadia}}"

run_sql() {
    psql "$PG_URL" -X -P pager=off -A -t -c "$1"
}

# Tiny shim around psql for tabular output.
run_table() {
    psql "$PG_URL" -X -P pager=off -c "$1"
}

echo
echo "=== Cascade overview (last 5 minutes) ==="
run_table "
SELECT
    COUNT(*)                                                   AS total_requests,
    SUM(CASE WHEN escalated THEN 1 ELSE 0 END)                 AS escalated,
    ROUND(100.0 * SUM(CASE WHEN escalated THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) AS escalation_rate_pct,
    AVG(elapsed_ms)::int                                       AS avg_elapsed_ms,
    SUM(prompt_tokens)                                         AS total_prompt_tokens,
    SUM(completion_tokens)                                     AS total_completion_tokens
FROM events
WHERE occurred_at > NOW() - INTERVAL '5 minutes'
  AND route = 'chat_completions';
"

echo "=== Per-final-model breakdown ==="
run_table "
SELECT
    model,
    COUNT(*) AS calls,
    SUM(completion_tokens) AS completion_tokens,
    ROUND(AVG(elapsed_ms)::numeric, 1) AS avg_elapsed_ms
FROM events
WHERE occurred_at > NOW() - INTERVAL '5 minutes'
GROUP BY model
ORDER BY calls DESC;
"

echo "=== Shadow pair throughput ==="
run_table "
SELECT
    COUNT(*) AS shadow_pairs,
    COUNT(*) FILTER (WHERE judged_at IS NULL) AS pending,
    COUNT(*) FILTER (WHERE judged_at IS NOT NULL) AS judged
FROM shadow_pairs
WHERE occurred_at > NOW() - INTERVAL '5 minutes';
"

echo "=== Judge scores (if Phase-3 poller running) ==="
run_table "
SELECT
    judge_name,
    prompt_variant,
    COUNT(*) AS scores,
    ROUND(AVG(score)::numeric, 3) AS mean_score,
    ROUND(AVG(elapsed_ms)::numeric, 1) AS avg_judge_ms
FROM judge_scores
WHERE occurred_at > NOW() - INTERVAL '5 minutes'
GROUP BY judge_name, prompt_variant
ORDER BY judge_name;
"
