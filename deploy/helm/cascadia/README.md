# Cascadia Helm chart

Deploy [Cascadia](https://github.com/cascadia-llm/cascadia) — a cascade-routing LLM gateway with a closed-loop quality measurement feedback loop — to Kubernetes.

> ⚠ **Chart version `0.0.1` — pre-1.0, no API stability guarantee.** The
> values.yaml schema may break between minor versions. Until an OCI / Helm-
> repo distribution exists ([see below](#distribution)), pin by **checking
> out a tagged git ref** before `helm install` — `helm install --version`
> only constrains *registry-based* installs and does NOT constrain a
> local-path install like `./deploy/helm/cascadia/`. See [Versioning &
> upgrades](#versioning--upgrades) and [`CHANGELOG.md`](CHANGELOG.md) before
> running `helm upgrade`.

## TL;DR (recommended — secrets via pre-created Secret)

The chart-created Secret path puts your API keys into `helm install --set`,
which writes them to `helm history` and shell history in plaintext. **Prefer
the pre-created Secret path below — it's the safe default.**

```bash
# 1. Create the Secret out-of-band (kubectl, sops, sealed-secrets, External
#    Secrets, whatever your secrets-management story is). Keys must match
#    Cascadia's env var names exactly. CASCADIA_DATABASE_URL is OPTIONAL —
#    without it the proxy serves requests but won't persist events, which
#    disables the closed-loop quality signal. Add it once you have Postgres.
$ kubectl create secret generic cascadia-secrets \
    --from-literal=CASCADIA_OPENAI_API_KEY=sk-... \
    --from-literal=CASCADIA_DATABASE_URL='postgres://user:pass@pg-host:5432/cascadia'

# 2. Check out the chart's tagged ref (so a `git pull` later doesn't move
#    the chart under your feet) and install pointing at the Secret.
$ git checkout helm-chart-v0.0.1   # tag name TBD once the OCI repo lands
$ helm install cascadia ./deploy/helm/cascadia \
    --set existingSecret=cascadia-secrets
```

<details>
<summary><b>Alternative: chart-managed Secret via <code>--set</code> (quick-test only, not for production)</b></summary>

```bash
$ helm install cascadia ./deploy/helm/cascadia \
    --set secrets.openaiApiKey=sk-... \
    --set secrets.databaseUrl="postgres://user:pass@pg-host:5432/cascadia"
```

The values you pass via `--set` are stored in plaintext in (a) your shell
history, (b) `helm history <release> --revision <n>`, (c) every Helm Secret
under `kube-system` (or wherever Helm stores release state). Rotating the
API key after a leak via `--set` requires deleting all helm history for the
release. Use this path only for ephemeral throwaway clusters.
</details>

The chart deploys the proxy only. The Python services (judge-worker, policy-controller, dashboard-api) and the Next.js dashboard each have their own deployment manifests (separate charts forthcoming; see `deploy/compose/docker-compose.full.yml` for the canonical service topology).

## Distribution

This chart is **distributed only as a local path inside the repo** today —
there is no `helm repo add cascadia https://...` yet, and no OCI registry
push. Plan of record: publish to `oci://ghcr.io/cascadia-llm/charts/cascadia`
once the chart hits `1.0.0`. Until then, clone the repo, `git checkout <tag>`,
and `helm install cascadia ./deploy/helm/cascadia`.

## Requirements

- Kubernetes 1.25+
- At least one upstream LLM provider API key (OpenAI / Anthropic / Groq / xAI) **or** a private OpenAI-compatible endpoint (vLLM, Together, DeepInfra). This is the only hard requirement; the proxy refuses to start without it.
- **Optional but strongly recommended:** a Postgres database for the event log + shadow_pairs. Without it the proxy serves traffic, but no events / shadow_pairs / judge_scores get written and the closed-loop quality signal is off. The chart deliberately does NOT bundle Postgres — use [bitnami/postgresql](https://artifacthub.io/packages/helm/bitnami/postgresql) or your managed instance.

## Configuration

See [`values.yaml`](values.yaml) for the full reference. Most-used knobs:

| Key | Default | Description |
|---|---|---|
| `replicaCount` | `2` | Number of proxy pods. Cascadia is stateless on the hot path. |
| `image.tag` | `.Chart.AppVersion` | Override image tag (e.g. for a SHA-pinned deploy). |
| `secrets.openaiApiKey` | `""` | OpenAI API key. At least one provider key is required. |
| `secrets.anthropicApiKey` | `""` | Anthropic API key. |
| `secrets.groqApiKey` | `""` | Groq API key. |
| `secrets.xaiApiKey` | `""` | xAI API key. |
| `secrets.databaseUrl` | `""` | Postgres URL for event + shadow_pair persistence. |
| `existingSecret` | `""` | Reference a pre-created `Secret` with `CASCADIA_*` keys instead of letting the chart create one (recommended for secrets-management integrations). |
| `config.openaiBaseUrl` | `https://api.openai.com` | Override to point at a private OpenAI-compatible endpoint — vLLM, Together, DeepInfra. See **Air-gapped / private upstreams** below. |
| `config.policy` | `""` | Inline policy file JSON. If set, the chart mounts it as `/etc/cascadia/policy.json` and sets `CASCADIA_POLICY_FILE` accordingly. If empty, the proxy boots with a single default cluster (from env-var fallbacks). **Must be set via a values file (`-f my-values.yaml`), not via `--set` — Helm parses the JSON braces as a Go map and the template errors out with `wrong type for value`.** See the [Multi-cluster policy](#multi-cluster-policy) example. |
| `config.clusterBuckets` | `""` | Number of classifier hash-buckets. Leave empty to inherit the proxy default (1, single cluster). Set when running a multi-cluster policy. |
| `config.persistBodies` | `false` | Persist verbatim `request_body` + `response_body` in the events table. **⚠ Defaults to `false` for privacy, but a regulated PII-free deployment usually wants `true`** so the judge worker has full bodies to score. See [Data residency](#data-residency) for the three postures (full / redacted / shadow-disabled) and pick one explicitly. |
| `config.redactShadowBodies` | `false` | SHA-256 the `shadow_pairs.{prompt,cheap_response,expensive_response}` columns. Disables the closed-loop quality score but preserves cascade metadata. See `SECURITY.md` for the trade-off. |
| `telemetry.otlpEndpoint` | `""` | OTLP/HTTP endpoint for trace export. |
| `networkPolicy.enabled` | `false` | Generate a `NetworkPolicy` restricting ingress + egress. See **Air-gapped / private upstreams** below. |
| `autoscaling.enabled` | `false` | Toggle the HorizontalPodAutoscaler. |
| `serviceMonitor.enabled` | `false` | Create a Prometheus Operator `ServiceMonitor`. |
| `podDisruptionBudget.enabled` | `false` | Create a `PodDisruptionBudget`. Recommended for HA. |

## Probes

- `livenessProbe` → `GET /livez` — process-up check, no DB or upstream dependency.
- `readinessProbe` → `GET /readyz` — DB pool reachable + at least one provider configured.
- `GET /health` is preserved as a backwards-compatible alias for `/readyz`.

Tune timing under `probes:` in `values.yaml`.

## Endpoints exposed by the proxy

- `POST /v1/chat/completions` — OpenAI-compatible chat. The hot path.
- `GET /livez` — liveness.
- `GET /readyz` — readiness with diagnostic JSON (`passed_checks`, `failed_checks`).
- `GET /health` — alias for `/readyz`.
- `GET /metrics` — Prometheus exposition (`cascadia_proxy_requests_total`, `cascadia_proxy_request_duration_seconds`).

## Air-gapped / private upstreams

Cascadia is designed to run with **no outbound internet beyond the upstream provider hosts you configure.** No telemetry, no remote-config fetch, no auto-update probes.

### Adding a provider (Mistral, DeepSeek, Together, vLLM, private endpoints)

See [`docs/adding-a-provider.md`](../../docs/adding-a-provider.md) for the full recipe. The Helm-flavored short version: any provider that speaks OpenAI's `/v1/chat/completions` shape is a one-line `config.openaiBaseUrl` override — no chart code changes, no new adapter. Use the `openai/` prefix in your policy regardless of the upstream's actual name.

```yaml
# Public Mistral API
config:
  openaiBaseUrl: https://api.mistral.ai/v1
secrets:
  openaiApiKey: "<mistral-key>"
```

```yaml
# Private vLLM / Together / DeepInfra cluster
config:
  openaiBaseUrl: https://vllm.internal.corp:8000
secrets:
  openaiApiKey: "internal-auth-token"   # whatever your cluster expects
```

The proxy is fine if multiple providers share the same `openai/` prefix — they're all routed through the same adapter at the override URL. For providers with their own wire format (Gemini, Bedrock native), a new adapter is required — see the docs page for the issue-first contribution path.

### Locking down egress with NetworkPolicy

Enable `networkPolicy.enabled` and customize the egress allowlist in `values.yaml`:

```yaml
networkPolicy:
  enabled: true
  egress:
    # DNS
    - to:
        - namespaceSelector: {}
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - { protocol: UDP, port: 53 }
    # Postgres
    - to:
        - ipBlock: { cidr: 10.0.0.0/8 }
      ports:
        - { protocol: TCP, port: 5432 }
    # Internal vLLM cluster
    - to:
        - ipBlock: { cidr: 10.50.0.0/16 }
      ports:
        - { protocol: TCP, port: 8000 }
```

Kubernetes `NetworkPolicy` is L3/L4; for DNS-name allowlisting use a CNI that supports L7 policies (Cilium, Calico Enterprise) and translate the egress rules to your CNI's CRD.

### Data residency

The default behaviour writes verbatim user prompts + both tier responses to `shadow_pairs.{prompt,cheap_response,expensive_response}` so the judge worker can score quality. Three postures are supported, ranked by restrictiveness:

1. **Full persistence** (default). Closed-loop quality scoring works.
2. **Redacted shadow bodies** — `config.redactShadowBodies: true`. Text columns become `sha256:` digests. The judge worker can correlate pairs but can't compare them. Cascade telemetry preserved.
3. **Shadow eval disabled** — set every cluster's `shadow_rate` to `0.0`. No shadow pairs written; closed loop is off.

Pick a posture explicitly. See `SECURITY.md` in the repo root for the full trade-off.

## Security context

- Pods run as non-root (`runAsUser: 65532`).
- `readOnlyRootFilesystem: true`.
- All capabilities dropped.
- `allowPrivilegeEscalation: false`.

Override under `podSecurityContext:` / `securityContext:` if your environment needs different IDs.

## Operator notes

### Inspecting `NOTES.txt` from CI

`helm template --show-only templates/NOTES.txt` errors out because Helm treats
`NOTES.txt` specially — it isn't a manifest template. To get the rendered
NOTES from a CI lint job, use `--dry-run` instead:

```bash
$ helm install cascadia ./deploy/helm/cascadia --dry-run --debug 2>&1 | sed -n '/^NOTES:/,$p'
```

This pattern works for assertions like "the NetworkPolicy warning is present
when networkPolicy.enabled is set."

### Verifying the Anthropic-via-OpenAI footgun protection

The OpenAI adapter refuses to dial any URL whose host is a known non-OpenAI
provider (Anthropic, Gemini, AWS Bedrock) — returns HTTP 400 with a clear
remediation message before the request leaves the proxy. The protection is
unit-tested in `crates/proxy/src/upstream/openai_compat.rs`.

For an end-to-end verification with no real Anthropic key required, the repo
root ships a `Makefile` target that boots a proxy pointed at
`https://api.anthropic.com`, sends one chat request, and asserts on the
400 + adapter-rejection text. Recipe uses `curl --retry-connrefused` instead
of a fragile sleep:

```bash
$ make test-footgun
OK: 400 + clear error from adapter pre-network
```

Same pattern for the readiness contract:

```bash
$ make test-readyz
OK: /readyz has both passed_checks and failed_checks keys
```

`make verify` runs both plus the full `cargo test --workspace`.

## Versioning & upgrades

- The chart is pre-1.0 (current: `0.0.1`). The `values.yaml` schema is **not stable** between minor versions; expect renames and removals.
- **Pin the chart by git ref while distribution is local-path only.** `helm install --version X` does NOT constrain a local-path install (the flag only constrains registry-based installs against `helm repo` or OCI). The reliable lock is `git checkout <tag>` *before* `helm install ./deploy/helm/cascadia`.
- Once the chart is published to OCI / a Helm repo, `--version` will become the canonical pin. Until then it's a no-op for this chart.
- Every release lists breaking changes in [`CHANGELOG.md`](CHANGELOG.md). Read it *before* running `helm upgrade`.
- `helm upgrade --dry-run --debug` against the new ref is the cheapest way to spot rename / removal surprises before they hit production.
- The chart's `Chart.yaml` carries `version` (chart API version) and `appVersion` (Cascadia binary version). They move together for now; `appVersion` may diverge once the chart stabilizes.

## Multi-cluster policy

The chart's default install runs a single-cluster policy assembled from env-var fallbacks (one cheap model, one expensive model, one threshold). To run a real cascade with multiple clusters, set `config.policy` to your policy JSON via a values file:

```yaml
# my-values.yaml
config:
  clusterBuckets: 4
  policy: |
    {
      "default_cluster": "cluster-0",
      "cluster_buckets": 4,
      "version": "prod-policy-v1",
      "clusters": {
        "cluster-0": {
          "cluster_id": "cluster-0",
          "cheap_model":     "openai/gpt-4o-mini",
          "expensive_model": "openai/gpt-4o",
          "threshold": 0.7,
          "shadow_rate": 0.1
        },
        "cluster-1": {
          "cluster_id": "cluster-1",
          "cheap_model":     "groq/llama-3.3-70b",
          "expensive_model": "openai/gpt-4o",
          "threshold": 0.7,
          "shadow_rate": 0.1
        }
      }
    }
```

```bash
$ helm install cascadia ./deploy/helm/cascadia -f my-values.yaml \
    --set existingSecret=cascadia-secrets
```

The chart creates a `<release>-policy` ConfigMap, mounts it at `/etc/cascadia/policy.json`, and sets `CASCADIA_POLICY_FILE` to that path. **Do NOT try to set `config.policy` via `--set`** — Helm parses the JSON braces as a Go map and the template errors out (`wrong type for value`). Always use `-f values-file.yaml` for policy.

The policy controller refits cluster thresholds against `judge_scores` every ~5 minutes (its own service; see `services/policy-controller/`). The proxy hot-reloads `CASCADIA_POLICY_FILE` on `inotify` events, so the controller's `kubectl apply -f` of a new policy ConfigMap propagates without a pod restart.

## High availability

`replicaCount: 2` is the default, but **two pods on the same node is one node failure away from zero pods**. The chart now ships a default soft `podAntiAffinity` preferring `topologyKey: kubernetes.io/hostname` (best-effort spread across nodes). For hard guarantees:

1. Set `affinity:` in your values to use `requiredDuringSchedulingIgnoredDuringExecution` (no fallback) for true cross-node placement.
2. Enable `podDisruptionBudget.enabled: true` to keep ≥1 pod through voluntary disruptions (node drains, cluster upgrades).
3. Set `autoscaling.enabled: true` and tune `minReplicas` to your traffic floor.

## Ingress

The chart does NOT ship an Ingress template — Ingress controllers vary widely (nginx, traefik, contour, ALB, GKE GCE-Ingress, Istio Gateway) and the right shape depends on your cluster. Two patterns work today:

```yaml
# Option A — change Service type
service:
  type: LoadBalancer
```

```yaml
# Option B — bring your own Ingress, point it at the ClusterIP Service
# (rendered name: <release>-cascadia, port 8080)
```

Tracked as an open question for the chart's 0.1 cut. If you want a chart-managed Ingress, file a GitHub issue with which controller + TLS setup you need so the template ships matching the most common case.

## What's NOT in this chart yet

- Helm chart for the dashboard / dashboard-api / judge-worker / policy-controller — pending. Today, use `deploy/compose/docker-compose.full.yml` for the full stack.
- Postgres as a dependency — bring your own, the chart deliberately doesn't bundle one.
- Ingress template — see [Ingress](#ingress) above for the two workarounds.
- OCI / Helm-repo distribution — see [Distribution](#distribution) at the top. Local-path install only until 1.0.
