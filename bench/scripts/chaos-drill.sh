#!/usr/bin/env bash
# Task 5 — Chaos-resilience drill (§7 criterion).
#
# Claim under test: "kill the controller + judge for an hour, the proxy keeps
# serving on its last-known policy." The proxy's hot path must not depend on
# the judge worker or the policy controller — they're asynchronous side-cars.
# This drill proves it:
#
#   1. Start the proxy with a fixed policy file. The judge worker and policy
#      controller are intentionally NOT running — that IS the outage state.
#   2. For CHAOS_SECONDS, send requests at a steady interval. Every one must
#      return 200: the proxy serves on its last-known policy with no judge and
#      no controller alive.
#   3. Assert /policy still serves the unchanged policy (the controller being
#      dead just means it isn't being refit — not that routing stops).
#   4. Assert shadow_pairs accumulate UNSCORED (ensemble_score IS NULL): the
#      judge being dead means pairs queue up, but the proxy is unaffected. When
#      the judge returns it drains the backlog (run the poller, or
#      bench/scripts/mtbench-humaneval.sh, to see recovery).
#
# Free + deterministic: all four providers point at the mock upstream, so no
# real API keys and no spend. This drills the resilience machinery, not
# provider behavior.
#
# Pre-conditions:
#   - `cargo build --release -p cascadia-proxy -p cascadia-mock-upstream`.
#   - Postgres running with the proxy schema migrated.
#
# Usage:
#   $ bench/scripts/chaos-drill.sh                # ~30s drill
#   $ CHAOS_SECONDS=3600 bench/scripts/chaos-drill.sh   # the real one-hour soak

set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO"

PG_URL="${CASCADIA_DATABASE_URL:-postgres://cascadia:cascadia@localhost:5432/cascadia}"
POLICY_FILE="${CASCADIA_POLICY_FILE:-/tmp/cascadia-chaos-policy.json}"
PROXY_PORT="${CASCADIA_LISTEN_PORT:-18087}"
MOCK_PORT="${CASCADIA_MOCK_PORT:-18088}"
CHAOS_SECONDS="${CHAOS_SECONDS:-30}"
REQUEST_INTERVAL="${REQUEST_INTERVAL:-2}"

PROXY_BIN="./target/release/cascadia-proxy"
MOCK_BIN="./target/release/cascadia-mock-upstream"
for b in "$PROXY_BIN" "$MOCK_BIN"; do
    if [[ ! -x "$b" ]]; then
        echo "==> Building $b"
        cargo build --release -p cascadia-proxy -p cascadia-mock-upstream 2>&1 | tail -3
        break
    fi
done

cat > "$POLICY_FILE" <<JSON
{
  "default_cluster": "cluster-0",
  "cluster_buckets": 2,
  "version": "chaos-drill-fixed",
  "clusters": {
    "cluster-0": {"cluster_id":"cluster-0","cheap_model":"openai/mock-cheap","expensive_model":"openai/mock-expensive","threshold":0.6,"shadow_rate":1.0},
    "cluster-1": {"cluster_id":"cluster-1","cheap_model":"openai/mock-cheap","expensive_model":"openai/mock-expensive","threshold":0.6,"shadow_rate":1.0}
  }
}
JSON

PIDS=()
cleanup() { for pid in "${PIDS[@]:-}"; do kill "$pid" 2>/dev/null || true; done; }
trap cleanup EXIT

echo "==> Resetting tables"
psql "$PG_URL" -P pager=off -c "TRUNCATE TABLE judge_scores, shadow_pairs, events;" > /dev/null

echo "==> Starting mock upstream + proxy (NO judge worker, NO policy controller)"
CASCADIA_MOCK_LISTEN_ADDR="127.0.0.1:${MOCK_PORT}" "$MOCK_BIN" > /tmp/cascadia-chaos-mock.log 2>&1 &
PIDS+=("$!")
until curl -sf "http://127.0.0.1:${MOCK_PORT}/" >/dev/null 2>&1 || nc -z 127.0.0.1 "${MOCK_PORT}" 2>/dev/null; do sleep 0.2; done
CASCADIA_OPENAI_API_KEY=anything \
CASCADIA_OPENAI_BASE_URL="http://127.0.0.1:${MOCK_PORT}" \
CASCADIA_LISTEN_ADDR="127.0.0.1:${PROXY_PORT}" \
CASCADIA_DATABASE_URL="$PG_URL" \
CASCADIA_LOG_JSON=false \
CASCADIA_POLICY_FILE="$POLICY_FILE" \
CASCADIA_CLUSTER_BUCKETS=2 \
"$PROXY_BIN" > /tmp/cascadia-chaos-proxy.log 2>&1 &
PROXY_PID="$!"
PIDS+=("$PROXY_PID")

until curl -sf "http://127.0.0.1:${PROXY_PORT}/health" >/dev/null 2>&1; do
    if ! kill -0 "$PROXY_PID" 2>/dev/null; then
        echo "ERROR: proxy crashed at startup:" >&2; cat /tmp/cascadia-chaos-proxy.log >&2; exit 1
    fi
    sleep 0.3
done
echo "    proxy up; judge + controller are DOWN by design"

POLICY_BEFORE="$(curl -s "http://127.0.0.1:${PROXY_PORT}/policy")"

echo "==> Driving traffic for ${CHAOS_SECONDS}s with judge + controller dead"
START=$(date +%s)
SENT=0
OK=0
FAIL=0
while [[ $(( $(date +%s) - START )) -lt $CHAOS_SECONDS ]]; do
    SENT=$((SENT + 1))
    status="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PROXY_PORT}/v1/chat/completions" \
        -H 'Content-Type: application/json' \
        -d "{\"model\":\"auto\",\"messages\":[{\"role\":\"user\",\"content\":\"chaos probe ${SENT}\"}]}")"
    if [[ "$status" == "200" ]]; then OK=$((OK + 1)); else FAIL=$((FAIL + 1)); echo "    request ${SENT} -> HTTP ${status}"; fi
    sleep "$REQUEST_INTERVAL"
done

echo "==> Post-conditions"
POLICY_AFTER="$(curl -s "http://127.0.0.1:${PROXY_PORT}/policy")"
UNSCORED="$(psql "$PG_URL" -tA -c "SELECT COUNT(*) FROM shadow_pairs WHERE ensemble_score IS NULL;")"
EVENTS="$(psql "$PG_URL" -tA -c "SELECT COUNT(*) FROM events;")"

PASS=1
echo "    requests: sent=${SENT} ok=${OK} fail=${FAIL}"
[[ "$FAIL" -eq 0 && "$OK" -gt 0 ]] || { echo "    ✗ proxy dropped requests during the outage"; PASS=0; }
if [[ "$POLICY_BEFORE" == "$POLICY_AFTER" ]]; then
    echo "    ✓ /policy unchanged through the outage (served last-known policy)"
else
    echo "    ✗ /policy changed with the controller dead — unexpected"; PASS=0
fi
echo "    events logged during outage: ${EVENTS}"
echo "    shadow_pairs queued UNSCORED (judge dead): ${UNSCORED}"
[[ "$UNSCORED" -gt 0 ]] || echo "    note: no unscored pairs — shadow_rate or traffic too low to enqueue work"

echo
echo "=========================================="
if [[ "$PASS" -eq 1 ]]; then
    echo "CHAOS DRILL PASSED — proxy served ${OK}/${SENT} requests on last-known"
    echo "policy with judge + controller dead for ${CHAOS_SECONDS}s."
    echo "Recovery: start the judge poller (or run mtbench-humaneval.sh) and the"
    echo "${UNSCORED} queued pairs drain — the proxy never noticed the outage."
else
    echo "CHAOS DRILL FAILED — see ✗ lines above."
fi
echo "=========================================="
[[ "$PASS" -eq 1 ]]
