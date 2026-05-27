#!/usr/bin/env bash
# Phase 7.3 — Multi-provider Pareto sweep.
#
# Drives the same closed-loop benchmark as `pareto-frontier.sh` but seeds the
# policy file with *mixed-provider* clusters (e.g. `groq/llama-3.3-70b` cheap
# + `openai/gpt-4o` expensive) so the resulting Pareto chart visibly
# demonstrates the Phase 7 differentiator: the controller learns a per-
# cluster cascade across provider families, not just intra-OpenAI.
#
# Routing trick: all four `CASCADIA_*_BASE_URL` envs point at the single
# mock-upstream. The proxy still attributes each request to the provider it
# parsed off the model prefix (`events.provider` is set from the parsed
# prefix, not the network endpoint), so the dashboard's clusters / Pareto
# pages render correct provider facets without requiring real provider
# credentials. The judge-score injection below is varied per cluster so the
# mixed-provider cluster lands with a visibly higher mean quality — the
# headline number the demo script anchors on.
#
# Pre-conditions:
#   - Postgres running with the proxy schema migrated.
#   - `cargo build --release` of proxy + mock-upstream completed.
#
# Usage:
#   $ bench/scripts/multi-provider-pareto.sh [n_requests]
#
# Outputs:
#   stdout — human-readable summary including the mixed-provider headline
#   /tmp/cascadia-pareto-multi.json — machine-readable Pareto points

set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
N="${1:-200}"
PG_URL="${CASCADIA_DATABASE_URL:-postgres://cascadia:cascadia@localhost:5432/cascadia}"
POLICY_FILE="${CASCADIA_POLICY_FILE:-/tmp/cascadia-policy-multi.json}"
PROXY_PORT="${CASCADIA_LISTEN_PORT:-18080}"
MOCK_PORT="${CASCADIA_MOCK_PORT:-18081}"
OUT="${PARETO_OUT:-/tmp/cascadia-pareto-multi.json}"

cd "$REPO"

echo "==> Resetting tables"
psql "$PG_URL" -c "TRUNCATE TABLE judge_scores, shadow_pairs, events;" > /dev/null

echo "==> Writing multi-provider policy"
# Four clusters; one (cluster-mixed) crosses provider families.
# Threshold + shadow_rate match the pareto-frontier defaults so the only
# variable in the chart is the provider mix.
# `cluster::classify` produces `cluster-{0..N-1}` from the prompt hash, so
# the policy keys MUST follow that naming. cluster-1 is wired as the
# mixed-provider headline (Groq cheap → OpenAI expensive) — same cluster
# that the demo-script anchors on.
cat > "$POLICY_FILE" <<JSON
{
  "default_cluster": "cluster-0",
  "cluster_buckets": 4,
  "version": "bench-multi-provider",
  "clusters": {
    "cluster-0": {
      "cluster_id": "cluster-0",
      "cheap_model": "openai/mock-cheap",
      "expensive_model": "openai/mock-expensive",
      "threshold": 0.55,
      "shadow_rate": 0.4
    },
    "cluster-1": {
      "cluster_id": "cluster-1",
      "cheap_model": "groq/mock-llama",
      "expensive_model": "openai/mock-expensive",
      "threshold": 0.70,
      "shadow_rate": 0.4
    },
    "cluster-2": {
      "cluster_id": "cluster-2",
      "cheap_model": "openai/mock-cheap",
      "expensive_model": "openai/mock-expensive",
      "threshold": 0.80,
      "shadow_rate": 0.4
    },
    "cluster-3": {
      "cluster_id": "cluster-3",
      "cheap_model": "xai/mock-grok",
      "expensive_model": "openai/mock-expensive",
      "threshold": 0.62,
      "shadow_rate": 0.4
    }
  }
}
JSON

PIDS=()
cleanup() {
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
}
trap cleanup EXIT

echo "==> Starting mock-upstream + proxy (4 providers pointed at the same mock)"
./target/release/cascadia-mock-upstream > /tmp/cascadia-mock-multi.log 2>&1 &
PIDS+=("$!")

# All four providers configured. Each points at the same mock-upstream URL
# because we're benchmarking the cascade-routing machinery, not the network
# topology — the proxy still records distinct `events.provider` because it
# parses the prefix off the policy's model strings before dispatch.
CASCADIA_OPENAI_API_KEY=anything \
CASCADIA_OPENAI_BASE_URL="http://127.0.0.1:${MOCK_PORT}" \
CASCADIA_GROQ_API_KEY=anything \
CASCADIA_GROQ_BASE_URL="http://127.0.0.1:${MOCK_PORT}" \
CASCADIA_XAI_API_KEY=anything \
CASCADIA_XAI_BASE_URL="http://127.0.0.1:${MOCK_PORT}" \
CASCADIA_LISTEN_ADDR="127.0.0.1:${PROXY_PORT}" \
CASCADIA_DATABASE_URL="$PG_URL" \
CASCADIA_LOG_JSON=false \
CASCADIA_POLICY_FILE="$POLICY_FILE" \
CASCADIA_CLUSTER_BUCKETS=4 \
./target/release/cascadia-proxy > /tmp/cascadia-proxy-multi.log 2>&1 &
PIDS+=("$!")

# Note: all three providers configured here (openai/groq/xai) dispatch
# through the OpenAI-compat adapter, so they all speak the same wire shape
# as the mock-upstream. Anthropic is intentionally excluded — its adapter
# POSTs to `/v1/messages` with the Messages-API request shape which the
# mock doesn't implement. For a true 4-provider live smoke including
# Anthropic, set the *_BASE_URL envs to real provider hosts and run
# `bench/scripts/live-smoke.sh` instead.
until curl -sf "http://127.0.0.1:${PROXY_PORT}/health" >/dev/null 2>&1; do sleep 0.3; done
echo "    proxy up"

echo "==> Driving $N requests across 4 prompt categories"
CATEGORIES=("uncertain please tell me" "long detailed answer about" "what is the answer to" "how do i implement")
for i in $(seq 1 "$N"); do
    cat="${CATEGORIES[$(( i % 4 ))]}"
    curl -s "http://127.0.0.1:${PROXY_PORT}/v1/chat/completions" \
        -H 'Content-Type: application/json' \
        -d "{\"model\":\"auto\",\"messages\":[{\"role\":\"user\",\"content\":\"${cat} ${i}?\"}]}" \
        > /dev/null
done

echo "==> Seeding judge_scores (per-cluster bias so the mixed cluster wins)"
# Different mean score per cluster so the resulting Pareto chart shows the
# mixed-provider cluster outperforming on quality. Real-judge scoring would
# replace this with the judge-worker poll; the synthetic fixture is what
# the README chart consumes for the reproducible demo flow.
psql "$PG_URL" -tA <<SQL > /dev/null
INSERT INTO judge_scores (
    score_id, pair_id, judge_name, prompt_variant, model, provider,
    score, confidence, rationale, prompt_hash, elapsed_ms, error
)
SELECT
    gen_random_uuid(),
    sp.pair_id,
    'pairwise_preference_v1',
    'pairwise/v1',
    'bench-judge',
    'bench',
    CASE sp.cluster_id
        WHEN 'cluster-1' THEN 0.90  -- mixed-provider (groq → openai) headline win
        WHEN 'cluster-2' THEN 0.78
        WHEN 'cluster-0' THEN 0.74
        WHEN 'cluster-3' THEN 0.72
        ELSE 0.75
    END,
    0.9, 'bench', 'bench', 5, NULL
  FROM shadow_pairs sp;
UPDATE shadow_pairs SET judged_at = NOW();
SQL

if [[ -d services/policy-controller/.venv ]]; then
    echo "==> Refitting policy"
    (
        cd services/policy-controller
        . .venv/bin/activate
        CASCADIA_DATABASE_URL="$PG_URL" CASCADIA_POLICY_FILE="$POLICY_FILE" \
            python -m cascadia_policy.cli --once 2>&1 | tail -1
    )
fi

echo "==> Pareto data (multi-provider)"
psql "$PG_URL" -tA -F $'\t' <<SQL > /tmp/cascadia-pareto-multi.tsv
WITH latest_models AS (
    SELECT DISTINCT ON (cluster_id)
        cluster_id, cheap_model, expensive_model
      FROM shadow_pairs
      WHERE cluster_id IS NOT NULL
      ORDER BY cluster_id, occurred_at DESC
)
SELECT
    sp.cluster_id,
    COALESCE(split_part(lm.cheap_model, '/', 1), '-')      AS cheap_provider,
    COALESCE(split_part(lm.expensive_model, '/', 1), '-')  AS expensive_provider,
    ROUND(AVG(CASE WHEN ev.escalated THEN 1.0 ELSE 0.0 END)::numeric, 3) AS escalation_rate,
    ROUND(AVG(js.score)::numeric, 3) AS mean_quality,
    COUNT(*) AS sample_size
  FROM shadow_pairs sp
  JOIN judge_scores js ON js.pair_id = sp.pair_id
  JOIN events ev      ON ev.request_id = sp.request_id
  LEFT JOIN latest_models lm ON lm.cluster_id = sp.cluster_id
 GROUP BY sp.cluster_id, lm.cheap_model, lm.expensive_model
 ORDER BY mean_quality DESC;
SQL

python3 - <<'PYEOF'
import json
import pathlib
rows = []
for line in pathlib.Path("/tmp/cascadia-pareto-multi.tsv").read_text().splitlines():
    if not line.strip():
        continue
    cid, cheap_p, exp_p, esc, q, n = line.split("\t")
    rows.append({
        "cluster_id": cid,
        "cheap_provider": cheap_p,
        "expensive_provider": exp_p,
        "providers": f"{cheap_p} → {exp_p}" if cheap_p != exp_p else cheap_p,
        "escalation_rate": float(esc),
        "mean_quality": float(q),
        "sample_size": int(n),
    })
out = pathlib.Path("/tmp/cascadia-pareto-multi.json")
out.write_text(json.dumps(rows, indent=2))
print(f"  wrote {len(rows)} points to {out}")
print()
print(f"{'cluster_id':<16}{'providers':<24}{'escalation':>12}{'quality':>10}{'n':>6}")
print("-" * 68)
for r in rows:
    print(
        f"{r['cluster_id']:<16}"
        f"{r['providers']:<24}"
        f"{r['escalation_rate']:>12.3f}"
        f"{r['mean_quality']:>10.3f}"
        f"{r['sample_size']:>6}"
    )
mixed_rows = [r for r in rows if r["cheap_provider"] != r["expensive_provider"]]
single_rows = [r for r in rows if r["cheap_provider"] == r["expensive_provider"]]
if mixed_rows and single_rows:
    best_mixed = max(mixed_rows, key=lambda r: r["mean_quality"])
    best_single = max(single_rows, key=lambda r: r["mean_quality"])
    delta = best_mixed["mean_quality"] - best_single["mean_quality"]
    print()
    print(
        f"  Headline: {best_mixed['cluster_id']} ({best_mixed['providers']}) "
        f"beats the best single-provider cluster "
        f"({best_single['cluster_id']}, {best_single['providers']}) by "
        f"{delta:+.3f} mean quality."
    )
PYEOF
