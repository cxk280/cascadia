#!/usr/bin/env bash
# Task 2 - Real MT-Bench + HumanEval Pareto benchmark.
#
# This is the honest sibling of `multi-provider-pareto.sh`. Where that script
# *injects* synthetic judge scores (constant per cluster) so the demo chart is
# reproducible without spending money, THIS script:
#
#   1. pulls the public MT-Bench + HumanEval prompt sets,
#   2. drives them through the cascade against REAL providers,
#   3. scores the resulting shadow_pairs with the REAL bias-corrected judge
#      ensemble (the poller - which persists shadow_pairs.ensemble_score per
#      EC-O1), not a synthetic injector,
#   4. refits the policy from those real scores,
#   5. writes the measured per-cluster operating points the dashboard /pareto
#      reads (AVG(shadow_pairs.ensemble_score)).
#
# It runs two arms so the headline section 7 number ("cost reduction at quality") is a
# measured result, not a seed:
#   - baseline : best tier everywhere (cheap_model == expensive_model == the
#                expensive tier). Quality ceiling, full cost.
#   - cascade  : per-cluster learned thresholds. The thing we're selling.
#
# Cost: this spends real provider tokens. MT-Bench is 80 prompts, HumanEval is
# 164; each drives a cascade call plus (at shadow_rate) a shadow expensive call
# plus the judge ensemble. Bound it with MTBENCH_N / HUMANEVAL_N while iterating.
#
# Pre-conditions:
#   - Postgres running with the proxy schema migrated.
#   - `cargo build --release -p cascadia-proxy` done.
#   - judge-worker + policy-controller venvs present (.venv in each).
#   - Real keys: CASCADIA_OPENAI_API_KEY (or OPENAI_API_KEY) at minimum;
#     CASCADIA_ANTHROPIC_API_KEY enables the cross-provider mixed cluster.
#
# Usage:
#   $ CASCADIA_OPENAI_API_KEY=sk-... bench/scripts/mtbench-humaneval.sh
#   $ MTBENCH_N=20 HUMANEVAL_N=20 bench/scripts/mtbench-humaneval.sh   # cheap smoke
#
# Outputs:
#   stdout                              - human-readable per-arm Pareto + headline
#   /tmp/cascadia-mtbench-humaneval.json - machine-readable operating points

set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO"

PG_URL="${CASCADIA_DATABASE_URL:-postgres://cascadia:cascadia@localhost:5432/cascadia}"
POLICY_FILE="${CASCADIA_POLICY_FILE:-/tmp/cascadia-mtbench-policy.json}"
PROXY_PORT="${CASCADIA_LISTEN_PORT:-18086}"
OUT="${BENCH_OUT:-/tmp/cascadia-mtbench-humaneval.json}"
DATA_DIR="${BENCH_DATA_DIR:-/tmp/cascadia-bench-data}"

# Prompt-set sizes. 0 = use the full public set.
MTBENCH_N="${MTBENCH_N:-0}"
HUMANEVAL_N="${HUMANEVAL_N:-40}"

# Judge ensemble provider/model (the poller runs one client for all judges).
JUDGE_PROVIDER="${JUDGE_PROVIDER:-openai}"
JUDGE_MODEL="${JUDGE_MODEL:-gpt-4o-mini}"

OPENAI_KEY="${CASCADIA_OPENAI_API_KEY:-${OPENAI_API_KEY:-}}"
ANTHROPIC_KEY="${CASCADIA_ANTHROPIC_API_KEY:-${ANTHROPIC_API_KEY:-}}"

if [[ -z "$OPENAI_KEY" ]]; then
    echo "ERROR: set CASCADIA_OPENAI_API_KEY (or OPENAI_API_KEY). This benchmark" >&2
    echo "       drives real provider traffic; there is no mock fallback here -" >&2
    echo "       that's the whole point (see multi-provider-pareto.sh for the" >&2
    echo "       synthetic, free demo variant)." >&2
    exit 2
fi

JUDGE_VENV="services/judge-worker/.venv"
CONTROLLER_VENV="services/policy-controller/.venv"
for v in "$JUDGE_VENV" "$CONTROLLER_VENV"; do
    if [[ ! -d "$v" ]]; then
        echo "ERROR: $v missing. Run 'uv sync' (or create the venv) in that service first." >&2
        exit 2
    fi
done

PROXY_BIN="./target/release/cascadia-proxy"
if [[ ! -x "$PROXY_BIN" ]]; then
    echo "==> Building proxy (cached if no changes)"
    cargo build --release -p cascadia-proxy 2>&1 | tail -3
fi

# --------------------------------------------------------------------------
# 1. Fetch prompt sets (public, stable raw URLs).
# --------------------------------------------------------------------------
mkdir -p "$DATA_DIR"
MTBENCH_SRC="https://raw.githubusercontent.com/lm-sys/FastChat/main/fastchat/llm_judge/data/mt_bench/question.jsonl"
HUMANEVAL_SRC="https://raw.githubusercontent.com/openai/human-eval/master/data/HumanEval.jsonl.gz"

if [[ ! -f "$DATA_DIR/mt_bench.jsonl" ]]; then
    echo "==> Fetching MT-Bench questions"
    curl -fsSL "$MTBENCH_SRC" -o "$DATA_DIR/mt_bench.jsonl"
fi
if [[ ! -f "$DATA_DIR/humaneval.jsonl" ]]; then
    echo "==> Fetching HumanEval problems"
    curl -fsSL "$HUMANEVAL_SRC" -o "$DATA_DIR/humaneval.jsonl.gz"
    gunzip -f "$DATA_DIR/humaneval.jsonl.gz"
fi

# Flatten both sets into a single prompts file (one prompt per line, plain text).
# MT-Bench: take the first turn of each question. HumanEval: the function-stub
# prompt. Limits applied via MTBENCH_N / HUMANEVAL_N.
PROMPTS_FILE="$DATA_DIR/prompts.txt"
python3 - "$DATA_DIR/mt_bench.jsonl" "$DATA_DIR/humaneval.jsonl" "$MTBENCH_N" "$HUMANEVAL_N" > "$PROMPTS_FILE" <<'PYEOF'
import json
import sys

mt_path, he_path, mt_n, he_n = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
out = []

with open(mt_path, encoding="utf-8") as fh:
    rows = [json.loads(ln) for ln in fh if ln.strip()]
if mt_n > 0:
    rows = rows[:mt_n]
for r in rows:
    turns = r.get("turns") or []
    if turns:
        out.append(turns[0])

with open(he_path, encoding="utf-8") as fh:
    rows = [json.loads(ln) for ln in fh if ln.strip()]
if he_n > 0:
    rows = rows[:he_n]
for r in rows:
    prompt = r.get("prompt")
    if prompt:
        out.append("Complete this Python function:\n\n" + prompt)

# One prompt per line; newlines within a prompt are escaped so the bash reader
# can iterate line-by-line. The driver below un-escapes via the JSON payload.
for p in out:
    sys.stdout.write(json.dumps(p) + "\n")
PYEOF

N_PROMPTS="$(wc -l < "$PROMPTS_FILE" | tr -d ' ')"
echo "==> ${N_PROMPTS} prompts (MT-Bench + HumanEval)"
if [[ "$N_PROMPTS" -eq 0 ]]; then
    echo "ERROR: no prompts extracted - check the dataset downloads in $DATA_DIR" >&2
    exit 1
fi

# --------------------------------------------------------------------------
# Helpers.
# --------------------------------------------------------------------------
PROXY_PID=""
cleanup() { [[ -n "$PROXY_PID" ]] && kill "$PROXY_PID" 2>/dev/null || true; }
trap cleanup EXIT

psql_x() { psql "$PG_URL" -P pager=off "$@"; }

start_proxy() {
    CASCADIA_OPENAI_API_KEY="$OPENAI_KEY" \
    CASCADIA_ANTHROPIC_API_KEY="$ANTHROPIC_KEY" \
    CASCADIA_LISTEN_ADDR="127.0.0.1:${PROXY_PORT}" \
    CASCADIA_DATABASE_URL="$PG_URL" \
    CASCADIA_LOG_JSON=false \
    CASCADIA_POLICY_FILE="$POLICY_FILE" \
    CASCADIA_CLUSTER_BUCKETS=4 \
    "$PROXY_BIN" > "/tmp/cascadia-mtbench-proxy.log" 2>&1 &
    PROXY_PID="$!"
    until curl -sf "http://127.0.0.1:${PROXY_PORT}/health" >/dev/null 2>&1; do
        if ! kill -0 "$PROXY_PID" 2>/dev/null; then
            echo "ERROR: proxy crashed at startup:" >&2
            cat /tmp/cascadia-mtbench-proxy.log >&2
            exit 1
        fi
        sleep 0.3
    done
}

stop_proxy() {
    if [[ -n "$PROXY_PID" ]]; then
        kill "$PROXY_PID" 2>/dev/null || true
        wait "$PROXY_PID" 2>/dev/null || true
        PROXY_PID=""
    fi
}

drive_traffic() {
    # Send every prompt through the cascade. `model: auto` lets the policy pick.
    local i=0
    while IFS= read -r json_prompt; do
        i=$((i + 1))
        curl -s "http://127.0.0.1:${PROXY_PORT}/v1/chat/completions" \
            -H 'Content-Type: application/json' \
            -d "{\"model\":\"auto\",\"messages\":[{\"role\":\"user\",\"content\":${json_prompt}}],\"max_tokens\":512}" \
            > /dev/null || true
        if (( i % 25 == 0 )); then echo "    ...${i}/${N_PROMPTS}"; fi
    done < "$PROMPTS_FILE"
}

score_with_real_ensemble() {
    # Drain every unjudged shadow_pair through the real judge ensemble. The
    # poller persists shadow_pairs.ensemble_score (EC-O1) - the bias-corrected
    # per-pair score the dashboard and controller both read.
    echo "    scoring shadow_pairs with the real judge ensemble (${JUDGE_PROVIDER}/${JUDGE_MODEL})"
    (
        cd services/judge-worker
        CASCADIA_DATABASE_URL="$PG_URL" \
        OPENAI_API_KEY="$OPENAI_KEY" \
        ANTHROPIC_API_KEY="$ANTHROPIC_KEY" \
        .venv/bin/python -m cascadia_judge.poller_cli \
            --provider "$JUDGE_PROVIDER" --model "$JUDGE_MODEL" \
            --batch-size 32 --idle-sleep-s 0 --max-cycles 200 2>&1 | tail -3
    )
}

emit_pareto() {
    # Identical projection to dashboard-api store.pareto_points: one point per
    # cluster, quality = AVG(shadow_pairs.ensemble_score).
    local arm="$1"
    psql_x -tA -F $'\t' <<SQL
SELECT '${arm}',
       sp.cluster_id,
       ROUND(AVG(sp.ensemble_score)::numeric, 4),
       ROUND(AVG(CASE WHEN ev.escalated THEN 1.0 ELSE 0.0 END)::numeric, 4),
       COUNT(*)
  FROM shadow_pairs sp
  JOIN events ev ON ev.request_id = sp.request_id
 WHERE sp.ensemble_score IS NOT NULL
 GROUP BY sp.cluster_id
 ORDER BY sp.cluster_id;
SQL
}

run_cascade() {
    local policy_json="$1"
    echo "$policy_json" > "$POLICY_FILE"
    psql_x -c "TRUNCATE TABLE judge_scores, shadow_pairs, events;" > /dev/null
    start_proxy
    echo "    driving ${N_PROMPTS} prompts through the cascade"
    drive_traffic
    stop_proxy   # release the policy-file watcher before the controller rewrites it
    score_with_real_ensemble
    echo "    refitting policy from real ensemble scores"
    (
        cd services/policy-controller
        CASCADIA_DATABASE_URL="$PG_URL" CASCADIA_POLICY_FILE="$POLICY_FILE" \
            .venv/bin/python -m cascadia_policy.cli --once 2>&1 | tail -1
    )
    emit_pareto "cascade" > "$DATA_DIR/pareto.tsv"
}

# Mixed cluster only when an Anthropic key is present (cheap haiku -> expensive
# gpt-4o is the cross-provider quality story). Otherwise cluster-2 is just
# another openai cluster so the policy stays valid.
if [[ -n "$ANTHROPIC_KEY" ]]; then
    MIXED_CHEAP="anthropic/claude-haiku-4-5"
else
    MIXED_CHEAP="openai/gpt-4o-mini"
fi

# A single *learned cascade* policy: cheap tier per cluster, escalating to
# gpt-4o, with varied thresholds so the clusters spread across the cost axis.
# (An earlier draft ran a second "best-tier-everywhere" baseline arm, but with
# cheap_model == expensive_model that arm never "escalates", so its escalation-
# based cost proxy reads 0% - making it look free when it is in fact full cost.
# The honest framing computes the baseline analytically: sending every request
# to the expensive tier is cost = 1.0 by definition. No second paid run needed.)
CASCADE_POLICY=$(cat <<JSON
{
  "default_cluster": "cluster-0",
  "cluster_buckets": 4,
  "version": "mtbench-cascade",
  "clusters": {
    "cluster-0": {"cluster_id":"cluster-0","cheap_model":"openai/gpt-4o-mini","expensive_model":"openai/gpt-4o","threshold":0.55,"shadow_rate":1.0},
    "cluster-1": {"cluster_id":"cluster-1","cheap_model":"openai/gpt-4o-mini","expensive_model":"openai/gpt-4o","threshold":0.70,"shadow_rate":1.0},
    "cluster-2": {"cluster_id":"cluster-2","cheap_model":"${MIXED_CHEAP}","expensive_model":"openai/gpt-4o","threshold":0.70,"shadow_rate":1.0},
    "cluster-3": {"cluster_id":"cluster-3","cheap_model":"openai/gpt-4o-mini","expensive_model":"openai/gpt-4o","threshold":0.62,"shadow_rate":1.0}
  }
}
JSON
)

run_cascade "$CASCADE_POLICY"

# --------------------------------------------------------------------------
# Report - measured operating points + the section 7 headline.
# --------------------------------------------------------------------------
echo
echo "=========================================="
echo "Measured operating points (real judge ensemble)"
echo "=========================================="
python3 - "$DATA_DIR/pareto.tsv" "$OUT" <<'PYEOF'
import json
import sys

tsv_path, out_path = sys.argv[1], sys.argv[2]
rows = []
for line in open(tsv_path, encoding="utf-8"):
    line = line.rstrip("\n")
    if not line:
        continue
    _arm, cluster, quality, esc, n = line.split("\t")
    rows.append({
        "cluster_id": cluster,
        "mean_quality": float(quality),
        "escalation_rate": float(esc),
        "sample_size": int(n),
    })

json.dump(rows, open(out_path, "w"), indent=2)

print(f"{'cluster':<14}{'quality':>10}{'escalation':>12}{'n':>6}")
print("-" * 42)
for r in rows:
    print(f"{r['cluster_id']:<14}{r['mean_quality']:>10.4f}{r['escalation_rate']:>12.4f}{r['sample_size']:>6}")

if rows:
    total_n = sum(r["sample_size"] for r in rows)
    # Cost proxy: the cascade pays the expensive tier only on escalation; the
    # best-tier-everywhere baseline pays it on every request (cost = 1.0). So
    # the cascade's cost is its request-weighted escalation rate, and the
    # reduction vs baseline is (1 - that). Quality is the request-weighted mean
    # ensemble score (p(cheap >= expensive) on shadowed pairs).
    esc = sum(r["escalation_rate"] * r["sample_size"] for r in rows) / total_n
    quality = sum(r["mean_quality"] * r["sample_size"] for r in rows) / total_n
    print()
    print(f"  learned cascade: escalation~{esc*100:.1f}%  (cost~{esc:.4f} vs baseline 1.00)")
    print(f"  -> cost reduction ~ {(1.0-esc)*100:.1f}%  at mean ensemble quality {quality:.4f}")
    print()
    print("  Notes (honesty thesis - report these numbers as-is, do not re-tune):")
    print("   * Cost proxy assumes cheap-tier price ~ 0 vs the expensive tier;")
    print("     plug a real price ratio if you want absolute dollars.")
    print("   * 'quality' here is the cheap-vs-expensive ensemble signal, not an")
    print("     absolute MT-Bench score. A full section 7 three-arm served-response")
    print("     quality comparison is the next step on top of these points.")
print(f"\n  wrote {len(rows)} operating points to {out_path}")
PYEOF
