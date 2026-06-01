#!/usr/bin/env bash
# Cascadia local-dev quick start - one command to bring up the whole stack.
#
# Brings up Postgres, writes a starter policy, builds + starts the mock
# upstream and the proxy, drives synthetic traffic to populate the Pareto
# data, starts the dashboard-api, and runs the dashboard dev server in the
# foreground. Ctrl-C tears the background processes down.
#
#   $ ./scripts/quickstart.sh
#
# This is the fastest loop for hacking on the proxy itself (cargo build +
# Postgres in Docker). To run the entire stack as containers instead, use
# `deploy/compose/docker-compose.full.yml`. To deploy, see deploy/helm or the
# Railway walkthrough in PLAN.md section 9 (2026-05-20).
#
# Override any of these via the environment:
#   CASCADIA_DATABASE_URL   Postgres DSN (default: local docker-compose)
#   CASCADIA_POLICY_FILE    starter policy path (default: /tmp/cascadia-policy.json)
#   CASCADIA_LISTEN_PORT    proxy port (default: 8080)
#   QUICKSTART_TRAFFIC      synthetic requests to drive (default: 120; 0 = skip)
#   CASCADIA_AUTH_DISABLED  set "true" to skip the dashboard login gate locally

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

PG_URL="${CASCADIA_DATABASE_URL:-postgres://cascadia:cascadia@localhost:5432/cascadia}"
POLICY_FILE="${CASCADIA_POLICY_FILE:-/tmp/cascadia-policy.json}"
PROXY_PORT="${CASCADIA_LISTEN_PORT:-8080}"
TRAFFIC="${QUICKSTART_TRAFFIC:-120}"
COMPOSE="deploy/compose/docker-compose.yml"

MOCK_PID="" ; PROXY_PID="" ; API_PID=""
cleanup() {
  echo
  echo "[quickstart] shutting down background processes..."
  [ -n "$API_PID" ]   && kill "$API_PID"   2>/dev/null || true
  [ -n "$PROXY_PID" ] && kill "$PROXY_PID" 2>/dev/null || true
  [ -n "$MOCK_PID" ]  && kill "$MOCK_PID"  2>/dev/null || true
  echo "[quickstart] Postgres is left running. Tear it down with:"
  echo "             docker compose -f $COMPOSE down -v"
}
trap cleanup EXIT INT TERM

echo "[quickstart] 1/5 - bringing up Postgres..."
docker compose -f "$COMPOSE" up -d

# Step 2 writes a starter policy file (the knob semantics are echoed to the
# terminal below so they show at runtime). See "## Tuning for cost" in the
# README for the full table.
if [ ! -f "$POLICY_FILE" ]; then
  echo "[quickstart] 2/5 - writing starter policy -> $POLICY_FILE"
  echo "[quickstart]       model strings need a provider/ prefix (e.g. openai/...);"
  echo "[quickstart]       unprefixed values hard-fail at boot, by design."
  echo "[quickstart]       threshold = cheap-tier confidence floor: cheap is kept"
  echo "[quickstart]       when confidence >= threshold, else escalate. LOWER"
  echo "[quickstart]       threshold = more cheap accepted = less escalation = cheaper."
  echo "[quickstart]       shadow_rate = fraction of accepted-cheap responses mirrored"
  echo "[quickstart]       to the expensive tier for scoring. Against LIVE providers"
  echo "[quickstart]       that costs real money (0.05-0.10 sweet spot; 0.0 disables"
  echo "[quickstart]       the closed loop). Against the mock upstream below it's free."
  cat > "$POLICY_FILE" <<'EOF'
{
  "default_cluster": "default",
  "cluster_buckets": 4,
  "clusters": {
    "default": {
      "cheap_model": "openai/mock-cheap",
      "expensive_model": "openai/mock-expensive",
      "threshold": 0.7,
      "shadow_rate": 0.1
    }
  }
}
EOF
else
  echo "[quickstart] 2/5 - reusing existing policy at $POLICY_FILE"
fi

echo "[quickstart] 3/5 - building proxy + mock upstream (cargo build --release)..."
cargo build --release

# At least one provider key (OPENAI/ANTHROPIC/GROQ/XAI) must be set. The mock
# upstream accepts any non-empty value, so `mock` is fine for local dev.
"$REPO/target/release/cascadia-mock-upstream" >/tmp/cascadia-mock.log 2>&1 &
MOCK_PID=$!
echo "[quickstart]       mock upstream started (pid $MOCK_PID, log /tmp/cascadia-mock.log)"

CASCADIA_OPENAI_API_KEY=mock \
CASCADIA_OPENAI_BASE_URL=http://127.0.0.1:18081 \
CASCADIA_DATABASE_URL="$PG_URL" \
CASCADIA_POLICY_FILE="$POLICY_FILE" \
CASCADIA_CLUSTER_BUCKETS=4 \
CASCADIA_LISTEN_PORT="$PROXY_PORT" \
  "$REPO/target/release/cascadia-proxy" >/tmp/cascadia-proxy.log 2>&1 &
PROXY_PID=$!
echo "[quickstart]       proxy starting (pid $PROXY_PID, log /tmp/cascadia-proxy.log)"

echo "[quickstart]       waiting for proxy /readyz on :$PROXY_PORT..."
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:$PROXY_PORT/readyz" >/dev/null 2>&1; then
    echo "[quickstart]       proxy ready."
    break
  fi
  sleep 0.5
done

if [ "$TRAFFIC" != "0" ]; then
  echo "[quickstart] 4/5 - driving $TRAFFIC synthetic requests to populate Pareto data..."
  bench/scripts/pareto-frontier.sh "$TRAFFIC" || \
    echo "[quickstart]       (traffic driver returned non-zero; continuing)"
else
  echo "[quickstart] 4/5 - skipping synthetic traffic (QUICKSTART_TRAFFIC=0)"
fi

echo "[quickstart] 5/5 - starting dashboard-api + dashboard..."
(
  cd services/dashboard-api
  if [ -d .venv ]; then
    # shellcheck disable=SC1091
    . .venv/bin/activate
  fi
  CASCADIA_DATABASE_URL="$PG_URL" cascadia-dashboard-api
) >/tmp/cascadia-dashboard-api.log 2>&1 &
API_PID=$!
echo "[quickstart]       dashboard-api started (pid $API_PID, log /tmp/cascadia-dashboard-api.log)"

cd dashboard
echo "[quickstart]       installing dashboard deps (npm install)..."
npm install --silent

cat <<EOF

[quickstart] [ok] Stack is up.
             Proxy        ->  http://localhost:$PROXY_PORT  (OpenAI-compatible at /v1)
             Dashboard    ->  http://localhost:3000
             dashboard-api logs -> /tmp/cascadia-dashboard-api.log

             The operator dashboard is gated by login. First visit redirects to
             /signup - create an email + password account, then you're in.
             (Set CASCADIA_AUTH_DISABLED=true to skip the gate locally.)

             Press Ctrl-C to stop the proxy, mock upstream, and dashboard-api.

EOF

# Foreground - Ctrl-C here triggers the cleanup trap above.
CASCADIA_AUTH_DISABLED="${CASCADIA_AUTH_DISABLED:-}" npm run dev
