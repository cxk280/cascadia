# Models & Providers

> **Tier 2** · spec v0 · auto-approved 2026-05-18 · `models-providers.md`
> Inherits [Dashboard shell](dashboard-shell.md).

## Purpose

The catalog of which providers and models Cascadia knows about, their per-token costs, capabilities, and current availability. Operators add/remove providers here.

## Layout

```
Breadcrumb: Models & providers                                  [Add provider]
──────────────────────────────────────────────────────────────────────────────────
┌──────────────────────────────────────────────────────────────────────────────┐
│ Providers                                                                    │
│  ┌───────────┬─────────┬───────────────┬─────────┬──────────────────────┐   │
│  │ Provider  │ Status  │ Latency p99   │ Cost mo │ Models (count)        │   │
│  ├───────────┼─────────┼───────────────┼─────────┼──────────────────────┤   │
│  │ Anthropic │ ● OK    │ 1.4s          │ $221    │ 4                     │   │
│  │ OpenAI    │ ● OK    │ 980ms         │ $142    │ 6                     │   │
│  │ Bedrock   │ ● OK    │ 1.8s          │ $18     │ 3 (proxied Anthropic) │   │
│  │ vLLM-localhost│ ● OK│ 230ms         │ $0      │ 1 (Llama-3-70b)       │   │
│  └───────────┴─────────┴───────────────┴─────────┴──────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────────┘

Anthropic (selected, expanded)
┌──────────────────────────────────────────────────────────────────────────────┐
│  API key  sk-ant-…AB12  [rotate]  [test connection]    Last verified 4m ago  │
│                                                                              │
│  Models                                                                      │
│  ┌──────────────┬────────┬────────────┬────────────┬─────────────────────┐  │
│  │ Model        │ Tier   │ $/M in     │ $/M out    │ Used in clusters    │  │
│  ├──────────────┼────────┼────────────┼────────────┼─────────────────────┤  │
│  │ Haiku-3.5    │ cheap  │ $1.00      │ $5.00      │ 18                  │  │
│  │ Sonnet-3.7   │ mid    │ $3.00      │ $15.00     │ 17                  │  │
│  │ Opus-4       │ exp    │ $15.00     │ $75.00     │ 0 (used as judge)   │  │
│  │ Sonnet-3.7   │ judge  │ same       │ same       │ as ensemble member  │  │
│  └──────────────┴────────┴────────────┴────────────┴─────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Sections

1. **Provider table** — overview row per provider, expandable.
2. **Expanded provider panel** — API key management, per-model catalog.

## Components

Data table, expandable row, key-masked input, model row, button.

## States

- **Provider degraded:** status dot turns warn, expand panel shows recent error rate + suggested action.
- **Adding new provider:** modal wizard: pick provider type, paste key, test connection, select default models.
- **Local model (vLLM/Ollama):** different fields — endpoint URL instead of API key.

## Data

- `providers`: array of `{name, status, latency_p99_ms, cost_window, models[]}`.
- Per model: `{name, tier, input_cost_per_m, output_cost_per_m, used_in_clusters_count, capabilities[]}`.

## Interactions

- Add provider opens wizard.
- Rotate key opens secure input flow + grace period.
- Test connection: pings model with a known prompt.
- Cost cells: editable for local/self-hosted models (where Cascadia can't autodiscover pricing).

## Notes

- API keys are stored encrypted at rest. Display always masked. Rotation is grace-period style (old key valid for 5 min) to avoid downtime.
