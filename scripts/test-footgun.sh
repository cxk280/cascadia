#!/usr/bin/env bash
# Verify the OpenAI adapter refuses to dial non-OpenAI hosts (Anthropic,
# Gemini, AWS Bedrock) — Phase 7 footgun protection. End-to-end test that
# does not require any real provider key. Uses curl --retry-connrefused to
# avoid sleep-based race conditions.

set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PG_URL="${CASCADIA_DATABASE_URL:-postgres://cascadia:cascadia@localhost:5432/cascadia}"
POLICY_FILE="${CASCADIA_POLICY_FILE:-/tmp/cascadia-policy.json}"
PROXY_PORT="${CASCADIA_LISTEN_PORT:-8080}"
PROXY_BIN="$REPO/target/release/cascadia-proxy"

cd "$REPO"

pkill -9 -f cascadia-proxy 2>/dev/null || true
pkill -9 -f cascadia-mock 2>/dev/null || true
sleep 1

python3 -c 'import json; json.dump({"default_cluster":"default","cluster_buckets":4,"clusters":{"default":{"cheap_model":"openai/test-cheap","expensive_model":"openai/test-expensive","threshold":0.7,"shadow_rate":0.0}}}, open("'"$POLICY_FILE"'","w"))'

CASCADIA_OPENAI_API_KEY=test \
CASCADIA_OPENAI_BASE_URL=https://api.anthropic.com \
CASCADIA_DATABASE_URL="$PG_URL" \
CASCADIA_POLICY_FILE="$POLICY_FILE" \
CASCADIA_CLUSTER_BUCKETS=4 \
"$PROXY_BIN" > /tmp/cascadia-footgun.log 2>&1 &
PROXY_PID=$!
trap 'kill -9 "$PROXY_PID" 2>/dev/null || true' EXIT

curl --retry 10 --retry-connrefused --retry-delay 1 -sf \
    "http://127.0.0.1:${PROXY_PORT}/livez" > /dev/null

status=$(curl -s -o /tmp/footgun.body -w "%{http_code}" -X POST \
    "http://127.0.0.1:${PROXY_PORT}/v1/chat/completions" \
    -H 'Content-Type: application/json' \
    -d '{"model":"openai/test","messages":[{"role":"user","content":"hi"}]}')

if [ "$status" = "400" ] && grep -q "does not speak the OpenAI" /tmp/footgun.body; then
    echo "OK: 400 + clear error from adapter pre-network"
    exit 0
else
    echo "FAIL: expected 400 with adapter-rejection text"
    echo "  status=$status"
    echo "  body=$(cat /tmp/footgun.body)"
    exit 1
fi
