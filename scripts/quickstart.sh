#!/usr/bin/env bash
# Cascadia local-dev quick start - one command to bring up the whole stack.
#
# Two modes:
#   * default (mock)  - mock upstream + synthetic Pareto seed. No keys, no cost,
#                       fully offline. Fastest loop for hacking on the proxy.
#   * CASCADIA_LIVE=1 - LIVE data, standalone: the proxy talks to REAL providers
#                       (Anthropic cascade by default), real traffic generates
#                       real shadow pairs, a real multi-model judge panel scores
#                       them, and the controller refits live. This spends real
#                       API budget. Needs ANTHROPIC_API_KEY (cascade) +
#                       OPENAI_API_KEY (cross-family judge panel).
#
#   ./scripts/quickstart.sh                 # mock
#   CASCADIA_LIVE=1 ./scripts/quickstart.sh # live, standalone
#
# Every port has a preferred value and falls back to the next free port if it's
# taken. Override via the environment:
#   CASCADIA_DATABASE_URL   Postgres DSN (default: local docker-compose)
#   CASCADIA_POLICY_FILE    policy path (default: /tmp/cascadia-policy.json)
#   CASCADIA_LISTEN_PORT    preferred proxy port         (default: 8080)
#   CASCADIA_MOCK_PORT      preferred mock-upstream port (default: 18091)
#   CASCADIA_DASHBOARD_PORT preferred dashboard-api port (default: 18082)
#   DASHBOARD_PORT          preferred dashboard UI port  (default: 3000)
#   CASCADIA_PG_PORT        preferred Postgres host port (default: 5432)
#   QUICKSTART_TRAFFIC      requests to drive            (default: 120; 0 = skip)
#   CASCADIA_AUTH_DISABLED  set "true" to skip the dashboard login gate locally
#   DASHBOARD_MODE          "prod" (default, precompiled) | "dev" (hot-reload)
# Live-mode only:
#   CASCADIA_CHEAP_MODEL      default anthropic/claude-haiku-4-5
#   CASCADIA_EXPENSIVE_MODEL  default anthropic/claude-sonnet-4-6
#   CASCADIA_JUDGE_PANEL      default from services/judge-worker/calibration/judge_ensemble.json
#   CASCADIA_LIVE_SHADOW_RATE default 0.5 (fraction mirrored to expensive for judging)

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

POLICY_FILE="${CASCADIA_POLICY_FILE:-/tmp/cascadia-policy.json}"
TRAFFIC="${QUICKSTART_TRAFFIC:-120}"
COMPOSE="deploy/compose/docker-compose.yml"
LIVE="${CASCADIA_LIVE:-}"

# --- live-mode config + key checks (fail fast before docker/build) ----------
CHEAP_MODEL="${CASCADIA_CHEAP_MODEL:-anthropic/claude-haiku-4-5}"
EXPENSIVE_MODEL="${CASCADIA_EXPENSIVE_MODEL:-anthropic/claude-sonnet-4-6}"
LIVE_SHADOW_RATE="${CASCADIA_LIVE_SHADOW_RATE:-0.5}"
# Judge panel: env override, else the baked-in calibration config, else a
# sensible default. The poller reads $CASCADIA_JUDGE_PANEL.
JUDGE_PANEL="${CASCADIA_JUDGE_PANEL:-$(python3 -c 'import json,sys; print(",".join(json.load(open("services/judge-worker/calibration/judge_ensemble.json"))["default_panel"]))' 2>/dev/null || echo "openai:gpt-4o-mini")}"

_key_env_for() {
  case "$1" in
    openai) echo OPENAI_API_KEY ;;
    groq) echo GROQ_API_KEY ;;
    xai) echo XAI_API_KEY ;;
    anthropic) echo ANTHROPIC_API_KEY ;;
    *) echo "" ;;
  esac
}

# Portable indirect read: value of the env var whose NAME is $1, or empty.
# (Avoids `${!name:-}`, which isn't reliable on macOS bash 3.2.)
_indirect() { eval "printf '%s' \"\${$1:-}\""; }

if [ -n "$LIVE" ]; then
  echo "[quickstart] LIVE mode: real providers, real shadow pairs, real judge panel (real \$\$)."
  # Cascade key: the default cascade is Anthropic; derive the needed key from
  # the cheap-model prefix so a custom CASCADIA_CHEAP_MODEL still checks right.
  cascade_provider="${CHEAP_MODEL%%/*}"
  cascade_key_env="$(_key_env_for "$cascade_provider")"
  if [ -z "$cascade_key_env" ]; then
    echo "[quickstart] ERROR: unknown cascade provider '$cascade_provider' in CASCADIA_CHEAP_MODEL" >&2
    exit 1
  fi
  if [ -z "$(_indirect "$cascade_key_env")" ]; then
    echo "[quickstart] ERROR: $cascade_key_env must be set for the $cascade_provider cascade (CASCADIA_LIVE)." >&2
    exit 1
  fi
  # Judge keys: every provider named in the panel needs its key.
  for member in ${JUDGE_PANEL//,/ }; do
    jp="${member%%:*}"
    jenv="$(_key_env_for "$jp")"
    if [ -z "$jenv" ]; then
      echo "[quickstart] ERROR: unknown judge provider '$jp' in CASCADIA_JUDGE_PANEL" >&2
      exit 1
    fi
    if [ -z "$(_indirect "$jenv")" ]; then
      echo "[quickstart] ERROR: $jenv must be set for judge panel member '$member' (CASCADIA_LIVE)." >&2
      exit 1
    fi
    if [ "$jp" = "$cascade_provider" ]; then
      echo "[quickstart] WARNING: judge provider '$jp' matches the cascade provider; the anti-self-preference filter will discount those verdicts. Use a different family." >&2
    fi
  done
fi

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
# CASCADIA_DATABASE_URL so the proxy, dashboard-api, judge poller, and
# controller all share the resolved DSN. Use 127.0.0.1 (not localhost) to force
# IPv4 onto the published port.
DB_PORT="$(choose_db_port "${CASCADIA_PG_PORT:-5432}")"
export CASCADIA_PG_HOST_PORT="$DB_PORT"
if [ -n "${CASCADIA_DATABASE_URL:-}" ]; then
  PG_URL="$CASCADIA_DATABASE_URL"; OWN_DB=""   # user's DB - we never truncate it
else
  PG_URL="postgres://cascadia:cascadia@127.0.0.1:$DB_PORT/cascadia"; OWN_DB=1
fi
export CASCADIA_DATABASE_URL="$PG_URL"

PROXY_PORT="$(pick_port proxy        "${CASCADIA_LISTEN_PORT:-8080}")"
MOCK_PORT="$(pick_port mock-upstream "${CASCADIA_MOCK_PORT:-18091}")"
API_PORT="$(pick_port dashboard-api  "${CASCADIA_DASHBOARD_PORT:-18082}")"
DASH_PORT="$(pick_port dashboard     "${DASHBOARD_PORT:-3000}")"

MOCK_PID="" ; PROXY_PID="" ; API_PID="" ; JUDGE_PID="" ; CTRL_PID=""
cleanup() {
  echo
  echo "[quickstart] shutting down background processes..."
  for pid in "$API_PID" "$CTRL_PID" "$JUDGE_PID" "$PROXY_PID" "$MOCK_PID"; do
    [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  done
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

# --- step 2: policy ---------------------------------------------------------
if [ -n "$LIVE" ]; then
  echo "[quickstart] 2/5 - writing LIVE policy -> $POLICY_FILE"
  echo "[quickstart]       cascade: $CHEAP_MODEL  ->  $EXPENSIVE_MODEL  (shadow_rate=$LIVE_SHADOW_RATE)"
  echo "[quickstart]       judge panel: $JUDGE_PANEL"
  cat > "$POLICY_FILE" <<EOF
{
  "default_cluster": "default",
  "cluster_buckets": 4,
  "clusters": {
    "default": {
      "cheap_model": "$CHEAP_MODEL",
      "expensive_model": "$EXPENSIVE_MODEL",
      "threshold": 0.7,
      "shadow_rate": $LIVE_SHADOW_RATE
    }
  }
}
EOF
elif [ ! -f "$POLICY_FILE" ]; then
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

# --- step 3: build + proxy (+ mock in mock mode) ----------------------------
echo "[quickstart] 3/5 - building proxy + mock upstream (cargo build --release)..."
cargo build --release

if [ -n "$LIVE" ]; then
  # Live: proxy talks to the REAL provider. Anthropic cascade by default; the
  # provider key comes from the same env the cascade-key check validated above.
  cascade_provider="${CHEAP_MODEL%%/*}"
  cascade_key_env="$(_key_env_for "$cascade_provider")"
  proxy_env=(
    "CASCADIA_DATABASE_URL=$PG_URL"
    "CASCADIA_POLICY_FILE=$POLICY_FILE"
    "CASCADIA_CLUSTER_BUCKETS=4"
    "CASCADIA_LISTEN_ADDR=127.0.0.1:$PROXY_PORT"
  )
  cascade_key_val="$(_indirect "$cascade_key_env")"
  case "$cascade_provider" in
    anthropic) proxy_env+=("CASCADIA_ANTHROPIC_API_KEY=$cascade_key_val") ;;
    openai)    proxy_env+=("CASCADIA_OPENAI_API_KEY=$cascade_key_val") ;;
    groq)      proxy_env+=("CASCADIA_GROQ_API_KEY=$cascade_key_val") ;;
    xai)       proxy_env+=("CASCADIA_XAI_API_KEY=$cascade_key_val") ;;
  esac
  env "${proxy_env[@]}" \
    "$REPO/target/release/cascadia-proxy" >/tmp/cascadia-proxy.log 2>&1 &
  PROXY_PID=$!
  echo "[quickstart]       LIVE proxy starting on :$PROXY_PORT -> $cascade_provider (pid $PROXY_PID, log /tmp/cascadia-proxy.log)"
else
  # Mock: at least one provider key must be set; the mock accepts any value.
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
fi

echo "[quickstart]       waiting for proxy /readyz on :$PROXY_PORT..."
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:$PROXY_PORT/readyz" >/dev/null 2>&1; then
    echo "[quickstart]       proxy ready."
    break
  fi
  sleep 0.5
done

# --- step 4: traffic --------------------------------------------------------
if [ -n "$LIVE" ]; then
  # Clean slate: clear synthetic seed rows so the dashboard shows ONLY live
  # data (otherwise leftover rows from a prior mock run or seed-dev-postgres.py
  # linger in the dashboard's window and look hard-coded). Only ever touches
  # our own throwaway docker DB - never a user-supplied CASCADIA_DATABASE_URL.
  if [ -n "$OWN_DB" ] && [ "${CASCADIA_LIVE_KEEP_DATA:-}" != "1" ] && command -v psql >/dev/null 2>&1; then
    echo "[quickstart] 4/5 - clearing synthetic data for a clean live slate (CASCADIA_LIVE_KEEP_DATA=1 to keep)..."
    PGPASSWORD=cascadia psql "$PG_URL" -c "TRUNCATE TABLE judge_scores, shadow_pairs, events;" >/dev/null 2>&1 \
      || echo "[quickstart]       (couldn't clear tables; dashboard may show leftover rows)"
  elif [ -z "$OWN_DB" ]; then
    echo "[quickstart] 4/5 - using your CASCADIA_DATABASE_URL; NOT auto-clearing it (leftover rows may show)."
  fi
  if [ "$TRAFFIC" != "0" ]; then
    echo "[quickstart]       driving $TRAFFIC REAL requests through the cascade (real API cost)..."
    CATS=("Explain in one paragraph:" "Write a short function that" \
          "What is the capital of" "Give me a careful, detailed answer about")
    for i in $(seq 1 "$TRAFFIC"); do
      cat="${CATS[$(( i % 4 ))]}"
      curl -s "http://127.0.0.1:$PROXY_PORT/v1/chat/completions" \
        -H 'Content-Type: application/json' \
        -d "{\"model\":\"auto\",\"messages\":[{\"role\":\"user\",\"content\":\"${cat} topic ${i}?\"}]}" \
        >/dev/null || true
    done
    echo "[quickstart]       traffic done; shadow pairs are queued for the judge panel."
  else
    echo "[quickstart]       no auto-traffic (QUICKSTART_TRAFFIC=0); send your own and watch it populate."
  fi
elif [ "$TRAFFIC" != "0" ]; then
  # Mock: the self-contained pareto-frontier harness seeds synthetic data. It
  # runs its OWN ephemeral proxy+mock (18080/18081), which is why our mock
  # defaults to 18091.
  echo "[quickstart] 4/5 - driving $TRAFFIC synthetic requests to populate Pareto data..."
  bench/scripts/pareto-frontier.sh "$TRAFFIC" || \
    echo "[quickstart]       (traffic driver returned non-zero; continuing)"
else
  echo "[quickstart] 4/5 - skipping synthetic traffic (QUICKSTART_TRAFFIC=0)"
fi

# --- step 4.5 (live only): real judge panel + controller, running live ------
if [ -n "$LIVE" ]; then
  if [ -d services/judge-worker/.venv ]; then
    echo "[quickstart]       starting judge panel poller ($JUDGE_PANEL)..."
    (
      cd services/judge-worker
      # shellcheck disable=SC1091
      . .venv/bin/activate
      CASCADIA_DATABASE_URL="$PG_URL" CASCADIA_JUDGE_PANEL="$JUDGE_PANEL" \
        cascadia-judge-poll --batch-size 4
    ) >/tmp/cascadia-judge.log 2>&1 &
    JUDGE_PID=$!
    echo "[quickstart]       judge poller pid $JUDGE_PID (log /tmp/cascadia-judge.log)"
  else
    echo "[quickstart]       WARNING: services/judge-worker/.venv missing; skipping live judging (run 'uv sync' there)." >&2
  fi
  if [ -d services/policy-controller/.venv ]; then
    echo "[quickstart]       starting policy controller (refit loop)..."
    (
      cd services/policy-controller
      # shellcheck disable=SC1091
      . .venv/bin/activate
      CASCADIA_DATABASE_URL="$PG_URL" CASCADIA_POLICY_FILE="$POLICY_FILE" \
        cascadia-policy-controller --interval-seconds 30 --min-sample-size 5 \
          --lookback-minutes 1440
    ) >/tmp/cascadia-controller.log 2>&1 &
    CTRL_PID=$!
    echo "[quickstart]       controller pid $CTRL_PID (log /tmp/cascadia-controller.log)"
  else
    echo "[quickstart]       WARNING: services/policy-controller/.venv missing; skipping live refit (run 'uv sync' there)." >&2
  fi
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

# The dashboard runs in production mode by default: `next build` precompiles
# every route up front so navigation is instant (no on-demand "Compiling
# /route..." lag once the stack is up). Set DASHBOARD_MODE=dev for the
# hot-reloading dev server (routes compile lazily on first visit) when you're
# actively editing the dashboard.
DASHBOARD_MODE="${DASHBOARD_MODE:-prod}"
export CASCADIA_DASHBOARD_API_BASE="http://127.0.0.1:$API_PORT"
export CASCADIA_AUTH_DISABLED="${CASCADIA_AUTH_DISABLED:-}"

# Printed right before the foreground server starts. $1 = mode description.
print_ready() {
  _data="mock data (synthetic seed)"
  [ -n "$LIVE" ] && _data="LIVE data ($CHEAP_MODEL -> $EXPENSIVE_MODEL; judge panel $JUDGE_PANEL)"
  cat <<EOF

[quickstart] [ok] Stack is up - $_data
             Proxy        ->  http://localhost:$PROXY_PORT  (OpenAI-compatible at /v1)
             Dashboard    ->  http://localhost:$DASH_PORT  ($1)
             dashboard-api logs -> /tmp/cascadia-dashboard-api.log

             The operator dashboard is gated by login. First visit redirects to
             /signup - the FIRST account becomes admin. (CASCADIA_AUTH_DISABLED=true
             skips the gate locally.)

             Press Ctrl-C to stop the proxy, mock/judge/controller, and dashboard-api.

EOF
}

# Run `next` directly (not `npm run dev`/`start`, which hardcode -p 3000) so the
# resolved dashboard port takes effect. NOT exec'd, so the cleanup trap above
# still fires on Ctrl-C.
if [ "$DASHBOARD_MODE" = "dev" ]; then
  print_ready "dev mode: hot-reload on, routes compile on first visit"
  ./node_modules/.bin/next dev -p "$DASH_PORT"
else
  echo "[quickstart]       precompiling dashboard routes (next build) for instant navigation..."
  ./node_modules/.bin/next build
  print_ready "precompiled production build"
  ./node_modules/.bin/next start -p "$DASH_PORT"
fi
