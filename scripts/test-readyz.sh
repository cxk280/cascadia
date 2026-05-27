#!/usr/bin/env bash
# Verify /readyz emits both passed_checks and failed_checks (with [] when
# empty) so K8s probe scripts can rely on the keys always being present.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PG_URL="${CASCADIA_DATABASE_URL:-postgres://cascadia:cascadia@localhost:5432/cascadia}"
POLICY_FILE="${CASCADIA_POLICY_FILE:-/tmp/cascadia-policy.json}"
PROXY_PORT="${CASCADIA_LISTEN_PORT:-8080}"
MOCK_PORT="${CASCADIA_MOCK_PORT:-18081}"
PROXY_BIN="$REPO/target/release/cascadia-proxy"
MOCK_BIN="$REPO/target/release/cascadia-mock-upstream"

cd "$REPO"

pkill -9 -f cascadia-proxy 2>/dev/null || true
pkill -9 -f cascadia-mock 2>/dev/null || true
sleep 1

# Ensure a valid prefixed policy is in place so the proxy boots.
python3 -c 'import json; json.dump({"default_cluster":"default","cluster_buckets":4,"clusters":{"default":{"cheap_model":"openai/mock-cheap","expensive_model":"openai/mock-expensive","threshold":0.7,"shadow_rate":0.0}}}, open("'"$POLICY_FILE"'","w"))'

"$MOCK_BIN" > /tmp/cascadia-mock.log 2>&1 &
MOCK_PID=$!

CASCADIA_OPENAI_API_KEY=mock \
CASCADIA_OPENAI_BASE_URL="http://127.0.0.1:${MOCK_PORT}" \
CASCADIA_DATABASE_URL="$PG_URL" \
CASCADIA_POLICY_FILE="$POLICY_FILE" \
CASCADIA_CLUSTER_BUCKETS=4 \
"$PROXY_BIN" > /tmp/cascadia-readyz.log 2>&1 &
PROXY_PID=$!
trap 'kill -9 "$PROXY_PID" "$MOCK_PID" 2>/dev/null || true' EXIT

curl --retry 10 --retry-connrefused --retry-delay 1 -sf \
    "http://127.0.0.1:${PROXY_PORT}/livez" > /dev/null

body=$(curl -s "http://127.0.0.1:${PROXY_PORT}/readyz")

if echo "$body" | python3 -c 'import sys,json; d=json.load(sys.stdin); assert "passed_checks" in d and "failed_checks" in d, d'; then
    echo "OK: /readyz has both passed_checks and failed_checks keys"
    exit 0
else
    echo "FAIL: missing key in $body"
    exit 1
fi
