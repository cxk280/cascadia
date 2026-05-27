# API Keys

> **Tier 3** · spec v0 · auto-approved 2026-05-18 · `api-keys.md`
> Inherits [Dashboard shell](dashboard-shell.md).

## Purpose

Manage Cascadia-issued API keys that *client* apps use to call Cascadia. (Distinct from upstream provider keys, which live in Models & providers.) Lets the operator scope keys per-app, see usage, and rotate.

## Layout

```
Breadcrumb: API keys                                                  [Create key]
──────────────────────────────────────────────────────────────────────────────────
┌──────────────────────────────────────────────────────────────────────────────┐
│ Active keys                                                                  │
│ ┌──────────────────┬──────────────────┬──────────────┬─────────┬───────────┐ │
│ │ Name             │ Key (masked)     │ Requests 7d  │ Spend 7d│ Last seen │ │
│ ├──────────────────┼──────────────────┼──────────────┼─────────┼───────────┤ │
│ │ prod web         │ sk_live_ABCD…XY  │ 84,212       │ $221    │ 14:22:03  │ │
│ │ staging          │ sk_live_QRST…12  │ 412          │ $4.10   │ 1d ago    │ │
│ │ chris-laptop     │ sk_live_…Z8     │ 18           │ $0.14   │ 4d ago    │ │
│ │ + create         │                  │              │         │           │ │
│ └──────────────────┴──────────────────┴──────────────┴─────────┴───────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘

Selected: prod web
┌──────────────────────────────────────────────────────────────────────────────┐
│  Scopes:   ☑ chat.completions   ☑ embeddings   ☐ admin                       │
│  Rate limit: 100 req/s                                                        │
│  Cluster allow-list: all   (limit to ▾)                                       │
│                                                                              │
│  [Rotate key]   [Revoke]   [Edit]                                            │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Sections

1. **Active keys table** — masked, with usage.
2. **Selected key detail** — scopes, rate limit, cluster allow-list, danger actions.

## Components

Data table, key-mask reveal-on-hover (with copy), checkbox group, numeric input, danger button.

## States

- **Creating:** modal shows new key value once, urges copy.
- **Rotated:** old key still valid for 5 minutes; banner reminds.
- **Revoked:** row greyed; restore-within-24h CTA.

## Data

- `keys`: `[{id, name, key_masked, scopes, rate_limit_rps, allowed_clusters, created_at, last_seen}]`.

## Interactions

- Create key → modal with name + scopes + show-once token + copy.
- Click row → load detail; edit inline.
- Rotate → confirmation; old key auto-expires in 5 min.

## Notes

- Show-once token is critical — never display the key again after first reveal. Operators should know this is intentional.
