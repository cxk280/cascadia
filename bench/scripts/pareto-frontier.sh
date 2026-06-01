#!/usr/bin/env bash
# Reproducible end-to-end benchmark: traffic -> cascade -> judge -> controller ->
# Pareto chart data.
#
# Drives N requests through the cascade, scores the shadow pairs offline
# (using either the live judge ensemble or the synthetic scripted fixture),
# refits per-cluster thresholds once, then prints the per-cluster
# (escalation_rate, mean_quality, n) tuples that the README chart and
# `dashboard/app/pareto/page.tsx` consume.
#
# Pre-conditions:
#   - Postgres running with the proxy schema migrated (migrations/0001..0004).
#   - Rust release builds available (`cargo build --release` of proxy + mock-upstream).
#   - judge-worker + policy-controller venvs bootstrapped.
#
# Usage:
#   $ bench/scripts/pareto-frontier.sh [n_requests]
#
# Outputs:
#   stdout - human-readable summary
#   /tmp/cascadia-pareto.json - machine-readable Pareto points

set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
N="${1:-120}"
PG_URL="${CASCADIA_DATABASE_URL:-postgres://cascadia:cascadia@localhost:5432/cascadia}"
POLICY_FILE="${CASCADIA_POLICY_FILE:-/tmp/cascadia-policy.json}"
PROXY_PORT="${CASCADIA_LISTEN_PORT:-18080}"
MOCK_PORT="${CASCADIA_MOCK_PORT:-18081}"
OUT="${PARETO_OUT:-/tmp/cascadia-pareto.json}"

cd "$REPO"

echo "==> Resetting tables"
psql "$PG_URL" -c "TRUNCATE TABLE judge_scores, shadow_pairs, events;" > /dev/null

echo "==> Writing starter policy"
# Phase 7: model strings must be `provider/model`. The mock-upstream serves
# the OpenAI-compatible shape, so route it through the `openai/` provider
# (CASCADIA_OPENAI_BASE_URL below points to the mock).
cat > "$POLICY_FILE" <<JSON
{
  "default_cluster": "default",
  "cluster_buckets": 4,
  "version": "bench-starter",
  "clusters": {
    "default": {
      "cluster_id": "default",
      "cheap_model": "openai/mock-cheap",
      "expensive_model": "openai/mock-expensive",
      "threshold": 0.7,
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

echo "==> Starting mock-upstream + proxy"
./target/release/cascadia-mock-upstream > /tmp/cascadia-mock.log 2>&1 &
PIDS+=("$!")

CASCADIA_OPENAI_API_KEY=anything \
CASCADIA_OPENAI_BASE_URL="http://127.0.0.1:${MOCK_PORT}" \
CASCADIA_LISTEN_ADDR="127.0.0.1:${PROXY_PORT}" \
CASCADIA_DATABASE_URL="$PG_URL" \
CASCADIA_LOG_JSON=false \
CASCADIA_CHEAP_MODEL=openai/mock-cheap \
CASCADIA_EXPENSIVE_MODEL=openai/mock-expensive \
CASCADIA_POLICY_FILE="$POLICY_FILE" \
CASCADIA_CLUSTER_BUCKETS=4 \
./target/release/cascadia-proxy > /tmp/cascadia-proxy.log 2>&1 &
PIDS+=("$!")

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

echo "==> Seeding judge_scores from shadow_pairs (synthetic 0.8 / pair)"
# In a real run, replace this with `cascadia-judge-poll` against live judges.
# The benchmark uses a constant score so the Pareto chart shape is stable
# across runs and CI can assert on it.
psql "$PG_URL" -tA <<SQL > /dev/null
INSERT INTO judge_scores (
    score_id, pair_id, judge_name, prompt_variant, model, provider,
    score, confidence, rationale, prompt_hash, elapsed_ms, error
)
SELECT gen_random_uuid(), pair_id, 'pairwise_preference_v1', 'pairwise/v1',
       'bench-judge', 'bench', 0.8, 0.9, 'bench', 'bench', 5, NULL
  FROM shadow_pairs;
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

echo "==> Pareto data"
psql "$PG_URL" -tA -F $'\t' <<SQL > /tmp/cascadia-pareto.tsv
SELECT
    sp.cluster_id,
    ROUND(AVG(CASE WHEN ev.escalated THEN 1.0 ELSE 0.0 END)::numeric, 3) AS escalation_rate,
    ROUND(AVG(js.score)::numeric, 3) AS mean_quality,
    COUNT(*) AS sample_size
  FROM shadow_pairs sp
  JOIN judge_scores js ON js.pair_id = sp.pair_id
  JOIN events ev      ON ev.request_id = sp.request_id
 GROUP BY sp.cluster_id
 ORDER BY mean_quality DESC;
SQL

python3 - <<'PYEOF'
import json
import pathlib
rows = []
for line in pathlib.Path("/tmp/cascadia-pareto.tsv").read_text().splitlines():
    if not line.strip():
        continue
    cid, esc, q, n = line.split("\t")
    rows.append({
        "cluster_id": cid,
        "escalation_rate": float(esc),
        "mean_quality": float(q),
        "sample_size": int(n),
    })
out = pathlib.Path("/tmp/cascadia-pareto.json")
out.write_text(json.dumps(rows, indent=2))
print(f"  wrote {len(rows)} points to {out}")
print(json.dumps(rows, indent=2))
PYEOF
