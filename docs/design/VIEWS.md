# Cascadia — Views Index

> The complete inventory of UI views (mocks) required to satisfy Cascadia's architecture. **1 view = 1 mock = 1 spec file.** Specs in `docs/design/views/*.md` (with the lone exception of `landing-hero-spec.md` which predates this index and is referenced in-place).

**Last updated:** 2026-05-18

---

## Scope philosophy

This list reflects what a *real* self-hostable LLM-gateway product needs to operate — not the minimum demoable subset. Mocking the full surface area before any code lets us:

1. Validate the information architecture and navigation as a whole.
2. Discover shared components (cards, tables, charts, code blocks, modals) before building them piecemeal.
3. Make the portfolio artifact convincing: real products have ~25 screens, not 3.
4. Get content/copy decisions out of the way once.

**Not in scope (deliberately omitted):**

- Multi-tenant / team-workspace views — Cascadia is single-org self-hosted in v1. Revisit post-launch.
- ~~SSO / login / signup — self-hosted with a single admin in v1. Optional auth in v2.~~ **Superseded 2026-06-01** (PLAN.md §9): the operator dashboard now has first-class email + password auth (login #28 / signup #29 below). SSO / external IdP remains out of scope — auth is deliberately roll-our-own for a single-org self-hosted tool.
- Blog index / individual posts — Markdown rendered by the static site generator; no bespoke mock needed.
- Roadmap page — a section on the docs landing, not its own mock.
- Network-offline / connectivity-lost — UI pattern (toast/banner), not a standalone view.

---

## Tiers

Mocks are built in order. Higher tiers tell the portfolio story; lower tiers complete the surface area.

- **Tier 1** — essential for the portfolio narrative; the screens hiring managers will look at.
- **Tier 2** — strong supporting evidence that this is a real product, not three nice screens.
- **Tier 3** — completes the operator's daily-driver picture (config + onboarding).
- **Tier 4** — commodity screens. Light-spec, light-mock. Necessary for completeness, low effort each.

---

## The full list

### Marketing & public surfaces (no auth)

| #   | View                  | Slug                          | Tier | Status           | One-line                                                                |
| --- | --------------------- | ----------------------------- | ---- | ---------------- | ----------------------------------------------------------------------- |
| 01  | Landing page          | `landing-hero-spec.md` *(top-level)* | 1    | spec v0 approved · **mock v0 complete** · **mock v1 complete** | Marketing landing + GitHub README hero (one design, two renders). All 9 sections built: top nav, hero, three claims, quick start, how it works, headline numbers, comparison table, methodology callout, footer. |
| 02  | Docs index            | `views/docs-index.md`         | 4    | spec v0 approved · **mock v0 complete**     | Top-level docs landing: getting started, architecture, methodology…    |
| 03  | Architecture page     | `views/architecture-public.md`| 3    | spec v0 approved · **mock v0 complete**     | Public deep-dive on system architecture (links from landing + docs).   |
| 04  | Methodology page      | `views/methodology.md`        | 2    | spec v0 approved · **mock v0 complete**     | Eval methodology explainer: judges, calibration, agreement statistics. |
| 05  | Benchmarks page       | `views/benchmarks.md`         | 3    | spec v0 approved · **mock v0 complete**     | Reproducible benchmark results with operating point on Pareto curve.   |
| 06  | Comparison page       | `views/comparison.md`         | 3    | spec v0 approved · **mock v0 complete**     | "Cascadia vs LiteLLM / Portkey / RouteLLM" with methodology notes.     |

### Authentication (pre-session, no auth)

| #   | View                  | Slug                          | Tier | Status           | One-line                                                                |
| --- | --------------------- | ----------------------------- | ---- | ---------------- | ----------------------------------------------------------------------- |
| 28  | Login                 | `views/login.md`              | 1    | spec v0 · **mock v0 complete** | Email + password sign-in; centered card on the dark canvas, redirects back to the requested page. |
| 29  | Signup                | `views/signup.md`             | 2    | spec v0 · **mock v0 complete** | Email + password account creation (display name optional, confirm-password); auto-signs-in on success. |

### Onboarding (post-install, pre-traffic)

| #   | View                  | Slug                          | Tier | Status        | One-line                                                                |
| --- | --------------------- | ----------------------------- | ---- | ------------- | ----------------------------------------------------------------------- |
| 07  | Cold-start            | `views/cold-start.md`         | 3    | spec v0 approved · **mock v0 complete**  | Just-installed empty state. Encourages first request + provider setup.  |
| 08  | First-run setup       | `views/first-run.md`          | 3    | spec v0 approved · **mock v0 complete**  | One-time wizard: provider API keys, model catalog, starter policy.     |

### Operator dashboard — live operations

| #   | View                  | Slug                          | Tier | Status        | One-line                                                                |
| --- | --------------------- | ----------------------------- | ---- | ------------- | ----------------------------------------------------------------------- |
| 09  | Overview              | `views/overview.md`           | 1    | spec v0 approved · **mock v0 complete** · **mock v0 complete** | Operator home: KPIs (savings, P99, quality), recent activity.          |
| 10  | Pareto frontier       | `views/pareto-frontier.md`    | 1    | spec v0 approved · **mock v0 complete** · **mock v0 complete** | THE chart, full-screen interactive: slider, operating point, scenarios.|
| 11  | Live traffic stream   | `views/live-traffic.md`       | 2    | spec v0 approved · **mock v0 complete**  | Real-time stream of requests with route decisions; filter + drill-in.  |
| 12  | Request detail        | `views/request-detail.md`     | 1    | spec v0 approved · **mock v0 complete**  | Per-request drill-down: classifier output, route decision, latencies.  |
| 13  | Cluster explorer      | `views/clusters.md`           | 1    | spec v0 approved · **mock v0 complete**  | Semantic clusters with per-cluster cost, quality, policy, traffic %.   |

### Operator dashboard — quality

| #   | View                  | Slug                          | Tier | Status        | One-line                                                                |
| --- | --------------------- | ----------------------------- | ---- | ------------- | ----------------------------------------------------------------------- |
| 14  | Quality history       | `views/quality-history.md`    | 2    | spec v0 approved · **mock v0 complete**  | Quality trend over time, per-cluster, with regression-alert overlays.  |
| 15  | Calibration           | `views/calibration.md`        | 2    | spec v0 approved · **mock v0 complete**  | Human-rates-LLM-pair interface; tracks judge agreement (Kendall's τ).  |

### Operator dashboard — cost

| #   | View                  | Slug                          | Tier | Status        | One-line                                                                |
| --- | --------------------- | ----------------------------- | ---- | ------------- | ----------------------------------------------------------------------- |
| 16  | Cost analytics        | `views/cost-analytics.md`     | 2    | spec v0 approved · **mock v0 complete**  | Spend over time; breakdown by cluster, model, API key; projections.    |

### Operator dashboard — health & ops

| #   | View                  | Slug                          | Tier | Status        | One-line                                                                |
| --- | --------------------- | ----------------------------- | ---- | ------------- | ----------------------------------------------------------------------- |
| 17  | System health         | `views/system-health.md`      | 1    | spec v0 approved · **mock v0 complete**  | Proxy / judge / controller / DB / queue status; SLO burn; deploy info. |
| 18  | Alerts & incidents    | `views/alerts.md`             | 3    | spec v0 approved · **mock v0 complete**  | Configurable alert rules and incident log.                              |

### Configuration

| #   | View                  | Slug                          | Tier | Status        | One-line                                                                |
| --- | --------------------- | ----------------------------- | ---- | ------------- | ----------------------------------------------------------------------- |
| 19  | Routing policy editor | `views/policy-editor.md`      | 1    | spec v0 approved · **mock v0 complete**  | Per-cluster thresholds; override; auto-tune toggle; policy history.    |
| 20  | Models & providers    | `views/models-providers.md`   | 2    | spec v0 approved · **mock v0 complete**  | Provider catalog: keys, models, costs, capabilities, enable/disable.   |
| 21  | Shadow routing config | `views/shadow-routing.md`     | 3    | spec v0 approved · **mock v0 complete**  | Shadow rate %, scheduling, cost budgeting, cluster-specific overrides. |
| 22  | Judge configuration   | `views/judge-config.md`       | 2    | spec v0 approved · **mock v0 complete**  | Judge ensemble setup: which models, which prompts, calibration source. |

### Settings & meta

| #   | View                  | Slug                          | Tier | Status        | One-line                                                                |
| --- | --------------------- | ----------------------------- | ---- | ------------- | ----------------------------------------------------------------------- |
| 23  | API keys              | `views/api-keys.md`           | 3    | spec v0 approved · **mock v0 complete**  | Cascadia-issued client keys (so client apps don't share upstream keys).|
| 24  | General settings      | `views/settings.md`           | 4    | spec v0 approved · **mock v0 complete**  | Org name, defaults, telemetry opt-in, retention, danger-zone actions.  |
| 25  | Audit log             | `views/audit-log.md`          | 4    | spec v0 approved · **mock v0 complete**  | Read-only history of config changes (who, when, what, before/after).   |

### Error / fallback states

| #   | View                  | Slug                          | Tier | Status        | One-line                                                                |
| --- | --------------------- | ----------------------------- | ---- | ------------- | ----------------------------------------------------------------------- |
| 26  | 404                   | `views/error-404.md`          | 4    | spec v0 approved · **mock v0 complete**  | Page-not-found state with helpful redirects.                            |
| 27  | 500 / unrecoverable   | `views/error-500.md`          | 4    | spec v0 approved · **mock v0 complete**  | Unrecoverable error with incident reporting affordance.                 |

---

## Cross-view design decisions

Decisions that apply across all views; spec files reference these rather than redefining:

- **Design tokens** — see `landing-hero-spec.md §2` and the `Cascadia Colors` variable collection in the Figma file. All views inherit dark default + light toggle, accent teal `#5AE3D6`, Inter/Inter Tight/JetBrains Mono type system, 8 px baseline.
- **Dashboard chrome** — every dashboard view (#09–#25) shares the same shell: top bar (org switcher, search, mode toggle, user menu), left sidebar nav, content area. Sidebar IA spec lives in `views/dashboard-shell.md`. The shell was first built in the Overview mock (node 25:2 in the Figma file) and is the reference layout for downstream dashboard mocks.
- **Empty / loading / error states** — every dashboard view's spec must declare its skeleton state and its zero-data state. Don't ship a view with a broken empty state.
- **Mobile responsiveness** — dashboard views are desktop-first (operators work on real monitors); we'll spec a graceful tablet view and a "use desktop" prompt at <768px. Public/marketing views are fully responsive per the landing spec.

---

## Mock-build order

When in doubt, build in this order:

1. **Landing** (in progress) — establishes the visual language.
2. **Overview** — establishes the dashboard chrome that 17 other views inherit.
3. **Pareto frontier explorer** — the headline interactive view.
4. **Cluster explorer + Request detail** — same data model, paired in users' mental model.
5. **Routing policy editor + System health** — round out Tier 1.
6. **Tier 2** in any order — each is independently valuable.
7. **Tier 3 + 4** in any order — these are commodity work.

---

## Status legend

- **spec v0 approved · **mock v0 complete**** — view is named here; spec file not yet written.
- **spec v0** — first draft written, awaiting (or has) approval.
- **spec v0 approved · **mock v0 complete**** — auto-approved per Chris's blanket approval on 2026-05-18.
- **mock in progress** — actively being built in Figma.
- **mock v0** — first version exists in Figma; awaiting iteration.
- **mock approved** — locked in until major design changes.
