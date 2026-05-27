# Cascadia Helm chart — CHANGELOG

This file tracks chart-only changes (the `version:` field in `Chart.yaml`), separate from the Cascadia binary version (`appVersion:`). Read this **before** running `helm upgrade`.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). All notable changes land here. Breaking changes are flagged ⚠.

---

## [0.0.1] — 2026-05-22

Initial chart. Ships with:

- Proxy Deployment + Service + ConfigMap + Secret.
- Optional NetworkPolicy (`networkPolicy.enabled`).
- Optional PodDisruptionBudget (`podDisruptionBudget.enabled`).
- Optional HorizontalPodAutoscaler (`autoscaling.enabled`).
- Optional ServiceMonitor for Prometheus Operator (`serviceMonitor.enabled`).
- Default secure pod context (non-root, read-only root, all caps dropped).
- Liveness/readiness probes split on `/livez` and `/readyz`.
- `config.policy` value — inline policy file JSON. When set, the chart creates a `<release>-policy` ConfigMap and mounts it at `/etc/cascadia/policy.json` with `CASCADIA_POLICY_FILE` env var pointing at it. Must be set via a values file, not `--set` (Helm parses the JSON as a Go map otherwise).
- `config.clusterBuckets` value — exposes the `CASCADIA_CLUSTER_BUCKETS` env var. Required for multi-cluster policies.
- Default soft `podAntiAffinity` rendered when `affinity:` is empty. Uses a templated label selector (`include "cascadia.name" .`) so `nameOverride:` doesn't silently disable the spread.
- `helm install` fail-guard: a bare install with no provider keys *and* no `existingSecret` errors out at template time with a clear remediation message. Previously a bare install rendered a valid-but-empty Secret and pods CrashLoopBackOff'd on startup.
- NOTES.txt warns about (a) chart-version pinning by git ref while distribution is local-path only, (b) the `persistBodies: false` default's effect on closed-loop quality.
- README sections: "Versioning & upgrades", "High availability", "Ingress", "Distribution" (OCI plan), "Multi-cluster policy".

⚠ **Pre-1.0 stability:** the values.yaml schema may break between any two minor versions. Lock the chart by `git checkout <tag>` before `helm install` — `helm install --version` does NOT constrain a local-path install. See [Versioning & upgrades](README.md#versioning--upgrades).

---

## Upgrade recipes

### From `main` (no pinned ref) to a tagged `0.0.x`

The chart at `0.0.1` is the first tagged release. If you've been pulling the chart from `main` without locking the git ref, your install may be missing the secret-guard, the templated anti-affinity, or future renames. Re-render and diff before upgrading:

```bash
$ git checkout <tag>   # e.g. helm-chart-v0.0.1 once the tag exists
$ helm get values cascadia > /tmp/cur-values.yaml
$ helm template cascadia ./deploy/helm/cascadia -f /tmp/cur-values.yaml > /tmp/new.yaml
$ helm get manifest cascadia > /tmp/cur.yaml
$ diff -u /tmp/cur.yaml /tmp/new.yaml
```

If the diff looks sane: `helm upgrade cascadia ./deploy/helm/cascadia -f /tmp/cur-values.yaml`.

> ℹ Note on `--version`: for local-path installs (`./deploy/helm/cascadia`) the `--version` flag is silently ignored — Helm only validates `--version` against `helm repo` or OCI registries. Lock the chart by `git checkout <tag>` instead.
