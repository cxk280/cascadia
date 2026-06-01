#!/usr/bin/env bash
# Phase 7 live smoke: one chat request per configured provider through the
# Cascadia proxy. Verifies that:
#   1. The proxy accepts the prefixed `provider/model` policy and boots.
#   2. Each adapter (openai_compat for OpenAI/Groq/xAI; anthropic translator)
#      successfully round-trips a real API call.
#   3. events.provider is attributed correctly per provider.
#   4. Tool-use parity (Phase 7.1) works end-to-end against Anthropic.
#
# Providers are tested only when their API key env var is set; missing keys
# are skipped with a clear note so this script is safe to run partially.
#
# Pre-conditions:
#   - cascadia-proxy built (`cargo build --release`).
#   - Postgres running with the proxy schema migrated.
#   - Any subset of:
#       OPENAI_API_KEY      (or CASCADIA_OPENAI_API_KEY)
#       ANTHROPIC_API_KEY   (or CASCADIA_ANTHROPIC_API_KEY)
#       GROQ_API_KEY        (or CASCADIA_GROQ_API_KEY)
#       XAI_API_KEY         (or CASCADIA_XAI_API_KEY)
#
# Usage:
#   $ OPENAI_API_KEY=sk-... ANTHROPIC_API_KEY=sk-... bench/scripts/live-smoke.sh
#
# Cost estimate: < $0.01 total (one short request per configured provider).

set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
PG_URL="${CASCADIA_DATABASE_URL:-postgres://cascadia:cascadia@localhost:5432/cascadia}"
POLICY_FILE="${CASCADIA_POLICY_FILE:-/tmp/cascadia-live-smoke-policy.json}"
PROXY_PORT="${CASCADIA_LISTEN_PORT:-18083}"

cd "$REPO"

# Accept either CASCADIA_*_API_KEY or the bare provider env var name.
OPENAI_KEY="${CASCADIA_OPENAI_API_KEY:-${OPENAI_API_KEY:-}}"
ANTHROPIC_KEY="${CASCADIA_ANTHROPIC_API_KEY:-${ANTHROPIC_API_KEY:-}}"
GROQ_KEY="${CASCADIA_GROQ_API_KEY:-${GROQ_API_KEY:-}}"
XAI_KEY="${CASCADIA_XAI_API_KEY:-${XAI_API_KEY:-}}"

# Build the policy table with one cluster per configured provider. The
# default_cluster is whichever provider has a key (preferring openai first).
TMP_DIR="$(mktemp -d)"
CLUSTERS_JSON=""
DEFAULT_CLUSTER=""

add_cluster() {
    local provider="$1"
    local cheap="$2"
    local expensive="$3"
    if [[ -n "$CLUSTERS_JSON" ]]; then CLUSTERS_JSON+=","; fi
    CLUSTERS_JSON+=$'\n'"    \"${provider}-cluster\": {\"cluster_id\": \"${provider}-cluster\", \"cheap_model\": \"${cheap}\", \"expensive_model\": \"${expensive}\", \"threshold\": 0.999, \"shadow_rate\": 0.0}"
    if [[ -z "$DEFAULT_CLUSTER" ]]; then DEFAULT_CLUSTER="${provider}-cluster"; fi
}

if [[ -n "$OPENAI_KEY" ]]; then
    add_cluster "openai" "openai/gpt-4o-mini" "openai/gpt-4o"
fi
if [[ -n "$ANTHROPIC_KEY" ]]; then
    add_cluster "anthropic" "anthropic/claude-haiku-4-5" "anthropic/claude-sonnet-4-5"
fi
if [[ -n "$GROQ_KEY" ]]; then
    add_cluster "groq" "groq/llama-3.3-70b-versatile" "groq/llama-3.3-70b-versatile"
fi
if [[ -n "$XAI_KEY" ]]; then
    add_cluster "xai" "xai/grok-2-latest" "xai/grok-2-latest"
fi

if [[ -z "$DEFAULT_CLUSTER" ]]; then
    echo "ERROR: no provider keys set. Set at least one of OPENAI_API_KEY / ANTHROPIC_API_KEY / GROQ_API_KEY / XAI_API_KEY"
    exit 2
fi

cat > "$POLICY_FILE" <<JSON
{
  "default_cluster": "${DEFAULT_CLUSTER}",
  "cluster_buckets": 0,
  "version": "live-smoke-$(date -u +%Y%m%dT%H%M%SZ)",
  "clusters": {${CLUSTERS_JSON}
  }
}
JSON

echo "==> Live-smoke policy written to ${POLICY_FILE}:"
cat "$POLICY_FILE" | head -40

echo "==> Building proxy (cached if no changes)"
cargo build --release -p cascadia-proxy 2>&1 | tail -3

PIDS=()
cleanup() {
    for pid in "${PIDS[@]:-}"; do
        kill "$pid" 2>/dev/null || true
    done
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT

echo "==> Starting proxy on port ${PROXY_PORT}"
CASCADIA_OPENAI_API_KEY="$OPENAI_KEY" \
CASCADIA_ANTHROPIC_API_KEY="$ANTHROPIC_KEY" \
CASCADIA_GROQ_API_KEY="$GROQ_KEY" \
CASCADIA_XAI_API_KEY="$XAI_KEY" \
CASCADIA_LISTEN_ADDR="127.0.0.1:${PROXY_PORT}" \
CASCADIA_DATABASE_URL="$PG_URL" \
CASCADIA_LOG_JSON=false \
CASCADIA_POLICY_FILE="$POLICY_FILE" \
CASCADIA_CHEAP_MODEL=openai/gpt-4o-mini \
CASCADIA_EXPENSIVE_MODEL=openai/gpt-4o \
./target/release/cascadia-proxy > "${TMP_DIR}/proxy.log" 2>&1 &
PIDS+=("$!")

until curl -sf "http://127.0.0.1:${PROXY_PORT}/health" >/dev/null 2>&1; do
    if ! kill -0 "${PIDS[0]}" 2>/dev/null; then
        echo "ERROR: proxy crashed at startup:"
        cat "${TMP_DIR}/proxy.log"
        exit 1
    fi
    sleep 0.3
done
echo "    proxy up"

PASS=()
FAIL=()
SMOKE_PAYLOAD='{"model":"auto","messages":[{"role":"user","content":"Reply with the single word \"pong\"."}],"max_tokens":16}'

smoke_provider() {
    local provider="$1"
    local cluster="${provider}-cluster"
    # The cascade classifier hashes the request into a bucket. We send the
    # request with a forced cluster id by setting a sentinel header that the
    # proxy passes through to classification - but in v0 there's no such
    # header, so we instead set cluster_buckets=0 (force default_cluster) and
    # rotate the default_cluster by patching the policy file once per smoke.
    cat > "$POLICY_FILE" <<JSON
{
  "default_cluster": "${cluster}",
  "cluster_buckets": 0,
  "version": "live-smoke-${provider}-$(date -u +%H%M%S)",
  "clusters": {${CLUSTERS_JSON}
  }
}
JSON
    sleep 1.5  # let the watcher pick up the new file
    echo "    request -> ${provider}"
    local out
    out="$(curl -sS -w '\nHTTP_STATUS=%{http_code}\n' "http://127.0.0.1:${PROXY_PORT}/v1/chat/completions" \
            -H 'Content-Type: application/json' \
            -d "$SMOKE_PAYLOAD" 2>&1)"
    local status
    status="$(echo "$out" | grep '^HTTP_STATUS=' | cut -d= -f2)"
    if [[ "$status" == "200" ]]; then
        local content
        content="$(echo "$out" | sed '/^HTTP_STATUS=/d' | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("choices",[{}])[0].get("message",{}).get("content","")[:80])' 2>/dev/null || echo "(parse fail)")"
        echo "      [OK] ${provider}: $content"
        PASS+=("$provider")
    else
        echo "      [X] ${provider}: HTTP $status"
        echo "$out" | sed '/^HTTP_STATUS=/d' | head -8
        FAIL+=("$provider")
    fi
}

echo "==> Smoking each configured provider"
[[ -n "$OPENAI_KEY"    ]] && smoke_provider "openai"
[[ -n "$ANTHROPIC_KEY" ]] && smoke_provider "anthropic"
[[ -n "$GROQ_KEY"      ]] && smoke_provider "groq"
[[ -n "$XAI_KEY"       ]] && smoke_provider "xai"

echo "==> events.provider attribution (last 10 minutes):"
psql "$PG_URL" -P pager=off -c "
SELECT provider, model, COUNT(*) AS n
  FROM events
 WHERE occurred_at > NOW() - INTERVAL '10 minutes'
 GROUP BY provider, model
 ORDER BY provider, model;
"

# Phase 7.1 tool-use parity smoke (Anthropic only, OpenAI tools[] roundtrip).
if [[ -n "$ANTHROPIC_KEY" ]]; then
    echo "==> Tool-use parity smoke (Anthropic adapter)"
    cat > "$POLICY_FILE" <<JSON
{
  "default_cluster": "anthropic-cluster",
  "cluster_buckets": 0,
  "version": "live-smoke-tools-$(date -u +%H%M%S)",
  "clusters": {${CLUSTERS_JSON}
  }
}
JSON
    sleep 1.5
    TOOL_PAYLOAD='{"model":"auto","messages":[{"role":"user","content":"What is the weather in SF? Use the tool."}],"max_tokens":256,"tools":[{"type":"function","function":{"name":"get_weather","description":"Get the weather in a city","parameters":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}}}]}'
    out="$(curl -sS -w '\nHTTP_STATUS=%{http_code}\n' "http://127.0.0.1:${PROXY_PORT}/v1/chat/completions" \
            -H 'Content-Type: application/json' \
            -d "$TOOL_PAYLOAD" 2>&1)"
    status="$(echo "$out" | grep '^HTTP_STATUS=' | cut -d= -f2)"
    if [[ "$status" == "200" ]]; then
        if echo "$out" | sed '/^HTTP_STATUS=/d' | python3 -c 'import sys,json; d=json.load(sys.stdin); calls=d.get("choices",[{}])[0].get("message",{}).get("tool_calls"); assert calls and len(calls)>0; assert calls[0]["function"]["name"]=="get_weather"; args=calls[0]["function"]["arguments"]; assert isinstance(args, str); json.loads(args); print("OK")' 2>/dev/null; then
            echo "      [OK] tool-use: Anthropic returned OpenAI-shape tool_calls with parseable arguments"
            PASS+=("anthropic-tools")
        else
            echo "      [X] tool-use: response did not round-trip cleanly"
            echo "$out" | sed '/^HTTP_STATUS=/d' | head -20
            FAIL+=("anthropic-tools")
        fi
    else
        echo "      [X] tool-use: HTTP $status"
        echo "$out" | sed '/^HTTP_STATUS=/d' | head -8
        FAIL+=("anthropic-tools")
    fi
fi

echo
echo "=========================================="
echo "PASSED: ${PASS[*]:-(none)}"
echo "FAILED: ${FAIL[*]:-(none)}"
echo "=========================================="

if [[ ${#FAIL[@]} -gt 0 ]]; then
    echo
    echo "==> Proxy log tail:"
    tail -40 "${TMP_DIR}/proxy.log"
    exit 1
fi
