#!/usr/bin/env bash
# Cascadia local-dev quick start - one command to bring up the whole stack.
#
# Brings up Postgres, writes a starter policy, builds + starts the mock
# upstream and the proxy, drives synthetic traffic to populate the Pareto
# data, starts the dashboard-api, and runs the dashboard dev server in the
# foreground. Ctrl-C tears the background processes down.
#
#   ./scripts/quickstart.sh
#
# This is the fastest loop for hacking on the proxy itself (cargo build +
# Postgres in Docker). To run the entire stack as containers instead, use
# `deploy/compose/docker-compose.full.yml`. To deploy, see deploy/helm or the
# Railway walkthrough in PLAN.md section 9 (2026-05-20).
#
# Every port has a preferred value and falls back to the next free port if
# that one is already taken (so it won't collide with another dev server).
# Override the preferred values via the environment:
#   CASCADIA_DATABASE_URL   Postgres DSN (default: local docker-compose)
#   CASCADIA_POLICY_FILE    starter policy path (default: /tmp/cascadia-policy.json)
#   CASCADIA_LISTEN_PORT    preferred proxy port         (default: 8080)
#   CASCADIA_MOCK_PORT      preferred mock-upstream port (default: 18091)
#   CASCADIA_DASHBOARD_PORT preferred dashboard-api port (default: 18082)
#   DASHBOARD_PORT          preferred dashboard UI port  (default: 3000)
#   QUICKSTART_TRAFFIC      synthetic requests to drive  (default: 120; 0 = skip)
#   CASCADIA_AUTH_DISABLED  set "true" to skip the dashboard login gate locally

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

POLICY_FILE="${CASCADIA_POLICY_FILE:-/tmp/cascadia-policy.json}"
TRAFFIC="${QUICKSTART_TRAFFIC:-120}"
COMPOSE="deploy/compose/docker-compose.yml"

# --- port helpers -----------------------------------------------------------
# port_in_use PORT -> exit 0 if something is LISTENing on it.
port_in_use() {
  _p="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$_p" -sTCP:LISTEN >/dev/null 2>&1
    return
  fi
  # Fallback when lsof is absent: probe both loopback families via bash
  # /dev/tcp (a connect that succeeds means something is listening).
  ( exec 3<>"/dev/tcp/127.0.0.1/$_p" ) 2>/dev/null && return 0
  ( exec 3<>"/dev/tcp/::1/$_p" )       2>/dev/null && return 0
  return 1
}

# pick_port LABEL PREFERRED -> echoes the preferred port, or the next free one
# above it if the preferred is taken. Progress goes to stderr so command
# substitution captures only the chosen port.
pick_port() {
  _label="$1"; _pref="$2"; _p="$_pref"; _tries=0
  while port_in_use "$_p"; do
    _tries=$((_tries + 1))
    if [ "$_tries" -gt 20 ]; then
      echo "[quickstart] ERROR: no free port for $_label near $_pref (tried 20)" >&2
      exit 1
    fi
    _next=$((_p + 1))
    echo "[quickstart]       $_label: port $_p is busy -> trying $_next" >&2
    _p="$_next"
  done
  [ "$_p" != "$_pref" ] && \
    echo "[quickstart]       $_label: preferred $_pref busy, using fallback $_p" >&2
  printf '%s\n' "$_p"
}

# db_is_ours PORT -> exit 0 if a Postgres answering on 127.0.0.1:PORT is the
# cascadia DB (right role + db). Lets us reuse our own container rather than
# treating it as a conflict (no port-creep across runs).
db_is_ours() {
  command -v psql >/dev/null 2>&1 || return 1
  PGPASSWORD=cascadia psql "postgresql://cascadia:cascadia@127.0.0.1:$1/cascadia" \
    -tAc 'select 1' >/dev/null 2>&1
}

# choose_db_port PREFERRED -> a host port to publish the cascadia container on.
# Uses the preferred port if it's free OR already our cascadia DB; otherwise a
# FOREIGN Postgres owns it (e.g. a Homebrew/Postgres.app install on 5432) and
# we skip to the next port so it can't shadow our container.
choose_db_port() {
  _pref="$1"; _p="$_pref"; _tries=0
  while :; do
    if ! port_in_use "$_p"; then printf '%s\n' "$_p"; return; fi
    if db_is_ours "$_p"; then printf '%s\n' "$_p"; return; fi
    _tries=$((_tries + 1))
    if [ "$_tries" -gt 20 ]; then
      echo "[quickstart] ERROR: no usable Postgres port near $_pref (tried 20)" >&2
      exit 1
    fi
    _n=$((_p + 1))
    echo "[quickstart]       postgres: :$_p is a non-cascadia server -> trying $_n" >&2
    _p="$_n"
  done
}

# Resolve the Postgres host port + DSN. The container always listens on 5432
# internally; CASCADIA_PG_HOST_PORT (read by docker-compose.yml) controls the
# host-side publish so a foreign Postgres on :5432 won't block us. We export
# CASCADIA_DATABASE_URL so the proxy, dashboard-api, and the pareto-frontier
# traffic driver all share the resolved DSN. Use 127.0.0.1 (not localhost) to
# force IPv4 onto the published port.
DB_PORT="$(choose_db_port "${CASCADIA_PG_PORT:-5432}")"
export CASCADIA_PG_HOST_PORT="$DB_PORT"
if [ -n "${CASCADIA_DATABASE_URL:-}" ]; then
  PG_URL="$CASCADIA_DATABASE_URL"
else
  PG_URL="postgres://cascadia:cascadia@127.0.0.1:$DB_PORT/cascadia"
fi
export CASCADIA_DATABASE_URL="$PG_URL"

PROXY_PORT="$(pick_port proxy        "${CASCADIA_LISTEN_PORT:-8080}")"
MOCK_PORT="$(pick_port mock-upstream "${CASCADIA_MOCK_PORT:-18091}")"
API_PORT="$(pick_port dashboard-api  "${CASCADIA_DASHBOARD_PORT:-18082}")"
DASH_PORT="$(pick_port dashboard     "${DASHBOARD_PORT:-3000}")"

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

echo "[quickstart] ports: postgres=$DB_PORT proxy=$PROXY_PORT mock=$MOCK_PORT dashboard-api=$API_PORT dashboard=$DASH_PORT"
echo "[quickstart] 1/5 - bringing up Postgres on host port $DB_PORT..."
docker compose -f "$COMPOSE" up -d
echo "[quickstart]       waiting for Postgres to accept connections on :$DB_PORT..."
for _ in $(seq 1 60); do
  if command -v psql >/dev/null 2>&1; then
    db_is_ours "$DB_PORT" && break
  else
    port_in_use "$DB_PORT" && break
  fi
  sleep 0.5
done

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
CASCADIA_MOCK_LISTEN_ADDR="127.0.0.1:$MOCK_PORT" \
  "$REPO/target/release/cascadia-mock-upstream" >/tmp/cascadia-mock.log 2>&1 &
MOCK_PID=$!
echo "[quickstart]       mock upstream started on :$MOCK_PORT (pid $MOCK_PID, log /tmp/cascadia-mock.log)"

# NOTE: the proxy reads CASCADIA_LISTEN_ADDR (host:port), not a bare port.
CASCADIA_OPENAI_API_KEY=mock \
CASCADIA_OPENAI_BASE_URL="http://127.0.0.1:$MOCK_PORT" \
CASCADIA_DATABASE_URL="$PG_URL" \
CASCADIA_POLICY_FILE="$POLICY_FILE" \
CASCADIA_CLUSTER_BUCKETS=4 \
CASCADIA_LISTEN_ADDR="127.0.0.1:$PROXY_PORT" \
  "$REPO/target/release/cascadia-proxy" >/tmp/cascadia-proxy.log 2>&1 &
PROXY_PID=$!
echo "[quickstart]       proxy starting on :$PROXY_PORT (pid $PROXY_PID, log /tmp/cascadia-proxy.log)"

echo "[quickstart]       waiting for proxy /readyz on :$PROXY_PORT..."
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:$PROXY_PORT/readyz" >/dev/null 2>&1; then
    echo "[quickstart]       proxy ready."
    break
  fi
  sleep 0.5
done

# Step 4 uses the self-contained pareto-frontier harness to seed Pareto data.
# It runs its OWN ephemeral proxy+mock (ports 18080/18081) and tears them down
# on exit, so it must not collide with our long-lived stack above - which is
# why our mock defaults to 18091, not 18081.
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
  CASCADIA_DATABASE_URL="$PG_URL" \
  CASCADIA_DASHBOARD_PORT="$API_PORT" \
  CASCADIA_PROXY_URL="http://127.0.0.1:$PROXY_PORT" \
    cascadia-dashboard-api
) >/tmp/cascadia-dashboard-api.log 2>&1 &
API_PID=$!
echo "[quickstart]       dashboard-api started on :$API_PORT (pid $API_PID, log /tmp/cascadia-dashboard-api.log)"

cd dashboard
echo "[quickstart]       installing dashboard deps (npm install)..."
npm install --silent

cat <<EOF

[quickstart] [ok] Stack is up.
             Proxy        ->  http://localhost:$PROXY_PORT  (OpenAI-compatible at /v1)
             Dashboard    ->  http://localhost:$DASH_PORT
             dashboard-api logs -> /tmp/cascadia-dashboard-api.log

             The operator dashboard is gated by login. First visit redirects to
             /signup - create an email + password account, then you're in.
             (Set CASCADIA_AUTH_DISABLED=true to skip the gate locally.)

             Press Ctrl-C to stop the proxy, mock upstream, and dashboard-api.

EOF

# Foreground - Ctrl-C here triggers the cleanup trap above. We invoke `next`
# directly (not `npm run dev`, which hardcodes -p 3000) so the resolved
# dashboard port takes effect, and point the UI + middleware at the resolved
# dashboard-api port.
CASCADIA_DASHBOARD_API_BASE="http://127.0.0.1:$API_PORT" \
CASCADIA_AUTH_DISABLED="${CASCADIA_AUTH_DISABLED:-}" \
  ./node_modules/.bin/next dev -p "$DASH_PORT"
