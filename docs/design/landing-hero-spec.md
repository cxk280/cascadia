# Landing / README Hero — Design Spec v0

> **Status:** v0 draft. Awaiting review before Figma work begins.
> **Artifact:** Single design that serves dual duty as (a) the OSS landing page (future Next.js) and (b) the GitHub README. Sections marked **[README]** also appear in the README; sections marked **[Landing only]** are interactive/animated and don't translate to GHFM.
> **Author:** Claude, on Chris's brief.
> **Last updated:** 2026-05-18.

---

## 1. Audience & goals

**Primary audience:**
1. MLOps engineers and technical evaluators scanning the repo (read time: 30 seconds before deciding "interesting" or "next").
2. Self-host curious developers comparing LLM gateways (read time: 2 minutes before deciding "try" or "skip").
3. ML systems people who read papers (FrugalGPT, RouteLLM, AutoMix) and want to see one shipped.

**Goals, in priority order:**
1. **Convey novelty in one chart.** The Pareto frontier with operating point is THE first impression. If they only look at one image, this is it.
2. **Establish technical credibility.** Real numbers, real architecture diagram, real code snippet, real papers cited. No marketing fluff.
3. **Make "try it" trivial.** A one-liner that anyone can copy-paste should be visible without scrolling past the fold.
4. **Signal technical depth.** Without stating it outright, the page should make it obvious that whoever built this has serious infra and ML systems chops.

**Anti-goals:**
- SaaS-marketing tone ("Transform your LLM costs with…"). No.
- Hero illustration with abstract gradients and 3D shapes. No.
- "Trusted by" logos. Don't have any; don't fake it.
- Animations for animations' sake. Every motion earns its place.

---

## 2. Visual direction

### Mood

Closer to **PostHog**, **Linear**, **Modal**, and **Plausible** than to **OpenAI**, **Anthropic**, or **Vercel marketing**. Specifically:

- Dense and technical, not breathy and aspirational.
- Restrained accent color usage — most of the page is neutral, accent reserved for the operating point on the Pareto chart and primary CTAs.
- Monospace appears prominently (developer aesthetic).
- Diagrams and charts are foreground, not decoration.

### Color tokens (proposed)

| Token            | Dark mode                | Light mode               | Use                                          |
| ---------------- | ------------------------ | ------------------------ | -------------------------------------------- |
| `bg.canvas`      | `#0B0D10` (near-black)   | `#FAFAF9` (warm white)   | Page background                              |
| `bg.surface`     | `#15181C`                | `#FFFFFF`                | Cards, code blocks                           |
| `bg.surface-2`   | `#1E2228`                | `#F4F4F2`                | Nested surfaces                              |
| `border.subtle`  | `#24292F`                | `#E5E5E2`                | Hairlines, dividers                          |
| `text.primary`   | `#E8EAED`                | `#1A1C1F`                | Body                                         |
| `text.secondary` | `#9BA1A8`                | `#5E646C`                | Captions, labels                             |
| `text.muted`     | `#6B7178`                | `#8A9099`                | Disclaimers                                  |
| `accent.primary` | `#5AE3D6` (cascade teal) | `#0E9F92`                | CTAs, operating-point dot, key highlights    |
| `accent.warn`    | `#F0B232`                | `#B17800`                | "Phase status" badges, "early access" notes  |
| `accent.danger`  | `#F26B6B`                | `#C03333`                | Anti-pattern callouts in comparison table    |

**Why cascade teal:** Cascadia evokes water (cascading), and a cool teal/cyan reads as both "flow" and "technical" without being clichéd Silicon Valley blue. It's distinguishable from the OpenAI green, Anthropic terracotta, LiteLLM blue palettes — important since we appear alongside them in comparison tables.

### Typography

| Role         | Family            | Size / weight (desktop)                 |
| ------------ | ----------------- | --------------------------------------- |
| Display (H1) | Inter 700         | 64 / 72 px, -0.03em tracking            |
| H2           | Inter 600         | 40 / 48 px, -0.02em tracking            |
| H3           | Inter 600         | 24 / 32 px                              |
| Subhead      | Inter 400         | 22 / 32 px                              |
| Body         | Inter 400         | 17 / 28 px                              |
| Small        | Inter 400         | 14 / 22 px                              |
| Code / mono  | JetBrains Mono 400| 14 / 22 px in body; 15 / 24 in blocks   |
| Eyebrow      | Inter 600 ALL CAPS| 12 px, 0.08em tracking                  |

> Inter Tight was the original spec but isn't in Figma's default font library. We fell back to Inter throughout, with slightly tighter tracking on display sizes (-0.03em / -0.02em) to compensate for the lost optical condensing. The visual difference at hero sizes is small.

Fallbacks: `system-ui, -apple-system, "Segoe UI", Roboto, …` so the page renders fast and looks consistent even pre-font-load.

### Layout grid

- Max content width: **1280 px** (1216 px inner, 32 px gutters).
- 12-column grid, 24 px gutters.
- Vertical rhythm baseline: 8 px. Section padding: 96 px desktop / 64 px tablet / 48 px mobile.
- Hero is full-bleed; everything else respects max-width.

---

## 3. Information architecture

Top-to-bottom on the landing page:

1. **Top nav** *(landing only — README has no equivalent)*
2. **Hero** — pitch + Pareto chart + primary CTAs *([README] adapted: H1, pitch, static Pareto image, CTAs as links)*
3. **The three claims** *([README])*
4. **Quick start** — copy-paste swap of OpenAI base URL *([README])*
5. **How it works** — simplified architecture diagram *([README])*
6. **Headline numbers** — benchmark callout *([README])*
7. **Comparison table** — vs LiteLLM, Portkey, RouteLLM, raw OpenAI *([README])*
8. **Eval methodology callout** — judge agreement, calibration ([README] abridged)
9. **Footer** *(landing only — README footer is minimal)*

---

## 4. Section specifications

### 4.1 Top nav *(landing only)*

**Layout (left to right):**
`Cascadia` wordmark (16 px, JetBrains Mono, weight 500) · spacer · `Docs` · `Architecture` · `Benchmarks` · `Blog` · spacer · GitHub star count + icon (live count via GitHub API).

**Behavior:** Sticky on scroll; gains a 1 px `border.subtle` bottom border + slight backdrop-blur once scrolled past the hero. Height 56 px collapsing to 48 px when sticky.

**Mobile:** Wordmark + hamburger; nav items collapse into a sheet.

---

### 4.2 Hero **[README]**

**Layout (desktop):** Two-column, ~55/45 split. Left: copy. Right: Pareto-frontier chart.

```
┌───────────────────────────────────────────────────────────────────────┐
│                                                                       │
│  ▸ OPEN SOURCE · MIT · PHASE 0                                        │
│                                                                       │
│  Cascadia                                                             │
│                                                                       │
│  The first LLM gateway that learns the cheapest model                 │
│  that still meets your quality bar — using counterfactual             │
│  evaluation on your live traffic, without a hand-maintained           │
│  golden dataset.                                                      │
│                                                                       │
│  ┌────────────┐  ┌────────────────┐                                   │
│  │ Get started│  │ Read the paper │                                   │
│  └────────────┘  └────────────────┘                                   │
│                                                                       │
│  ┌──────────────────────────────────────────────┐                     │
│  │ $ docker run -p 8080:8080 ghcr.io/.../cascadia│ ◀ copy button     │
│  └──────────────────────────────────────────────┘                     │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
                                                ┌──────────────────────┐
                                                │                      │
                                                │  Pareto frontier     │
                                                │  chart (see 4.2.1)   │
                                                │                      │
                                                │                      │
                                                └──────────────────────┘
```

**Copy:**

- Eyebrow: `OPEN SOURCE · MIT · PHASE 0` (color `text.secondary`, accent dot for "PHASE 0" in `accent.warn`).
- H1: `Cascadia` *(or alternative: tagline as H1 — see open question §9.1)*.
- Subhead (body large, 22 / 32 px): *"The first LLM gateway that learns the cheapest model that still meets your quality bar — using counterfactual evaluation on your live traffic, without a hand-maintained golden dataset."*
- Primary CTA: `Get started` (filled, `accent.primary` background, dark text) → scrolls to §4.4 Quick start.
- Secondary CTA: `Read the paper` (outline, `border.subtle`) → links to `/docs/methodology` (or `docs/methodology.md` on the README).
- Inline code snippet under CTAs: `docker run -p 8080:8080 ghcr.io/cascadia/proxy:latest` with a copy-to-clipboard button.

**README adaptation:**

```markdown
<p align="center">
  <img src="docs/assets/pareto-hero.svg" width="640" alt="Cascadia Pareto frontier with current operating point">
</p>

<h1 align="center">Cascadia</h1>

<p align="center">
  The first LLM gateway that learns the cheapest model that still meets your
  quality bar — using counterfactual evaluation on your live traffic, without a
  hand-maintained golden dataset.
</p>

<p align="center">
  <a href="#quick-start"><strong>Get started</strong></a> ·
  <a href="docs/methodology.md">Read the paper</a> ·
  <a href="docs/ARCHITECTURE.md">Architecture</a>
</p>
```

#### 4.2.1 Pareto frontier chart (hero visual)

The single most important pixel on the page.

**Content:**
- X axis: **Cost per 1k requests** (USD, log scale). Range: $0.10 → $30.
- Y axis: **Quality score** (% of "Sonnet-everywhere" baseline). Range: 70% → 100%.
- Plotted points: ~6–10 named model configurations as reference dots:
  - `Haiku-everywhere` (cheap, ~78% quality)
  - `Sonnet-everywhere` (expensive, 100% by definition)
  - `Opus-everywhere` (most expensive, ~102%)
  - `GPT-4o-everywhere`, `GPT-4o-mini-everywhere`, etc.
  - `Static cascade (manual threshold)`
  - **`Cascadia (learned)`** ← the operating-point dot, in `accent.primary`, slightly larger, with a callout label
- Pareto frontier curve drawn through the optimal non-dominated points. `Cascadia (learned)` sits visibly above and left of `Static cascade`.

**Animation [Landing only]:** On scroll into view, the points fade in left-to-right, then the curve draws itself, then the `Cascadia (learned)` dot enters with a 200ms ease-out scale + a subtle pulse for ~2s. No infinite animation — calm after settling.

**Hover [Landing only]:** Hovering any dot shows a tooltip: model name, cost/1k, quality %, link to "show me the routing this implies."

**README static:** Same chart as a flat SVG. Operating-point callout label is "in line" rather than tooltip.

**Caveat label (inset, `text.muted`):** "Numbers from `bench/v0` on MT-Bench + HumanEval, n=2,400 prompts. Reproduce: `make bench`."

---

### 4.3 Three claims **[README]**

Section heading: `H2: How it actually works` *(not "Features" — too vendor-y)*.

**Layout:** Three equal-width columns desktop; stacks on mobile.

**Each column:**
- Mono label (e.g., `01 · ROUTING`)
- H3 (the claim, ~24/32 px)
- Body (~3 lines)
- "Learn more →" link to the relevant docs anchor.

| Column          | Mono label                       | H3                                                                 | Body                                                                                                                                                                                                                                                                            |
| --------------- | -------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1               | `01 · ROUTING`                   | Counterfactual shadow routing                                      | A configurable slice of every cascade decision is mirrored to the next tier up. The "what would the expensive model have said?" signal is generated continuously, as a side effect of serving traffic. No separate eval rig to babysit.                                         |
| 2               | `02 · CLUSTERING`                | Per-cluster cascade policies                                       | A small embedder bins requests into semantic categories — code, math, simple Q&A, creative writing. Each cluster learns its own (cheap tier, expensive tier, escalation threshold) policy. Routing decisions are honest at the category level, not a single global threshold.   |
| 3               | `03 · TRADEOFF`                  | Live, navigable Pareto frontier                                    | Move a slider — "I want 98% of Sonnet-everywhere quality" — see the projected cost. The numbers come from real shadow data on your traffic, not synthetic benchmarks.                                                                                                          |

**Visual treatment:**
- Cards have `bg.surface` background, `border.subtle` 1 px hairline, no shadow.
- Mono label sits in `accent.primary` color.
- H3 in `text.primary`.
- Body in `text.secondary`.
- "Learn more" link in `accent.primary` with hover underline.

---

### 4.4 Quick start **[README]**

Section heading: `H2: Quick start`.

**Layout:** Two-column desktop. Left: tabbed install command. Right: minimal usage snippet.

**Left column — install tabs:**

Tabs: `Docker` | `Helm` | `Cargo` | `Source`

```
$ docker run -p 8080:8080 \
    -e CASCADIA_OPENAI_API_KEY=sk-... \
    -e CASCADIA_ANTHROPIC_API_KEY=sk-ant-... \
    ghcr.io/cascadia/proxy:latest
```

(Helm tab):
```
$ helm repo add cascadia https://cascadia.github.io/charts
$ helm install cascadia cascadia/cascadia
```

(Cargo tab):
```
$ cargo install cascadia-proxy
$ cascadia-proxy --config ./cascadia.toml
```

(Source tab):
```
$ git clone https://github.com/<TBD>/cascadia
$ cd cascadia && docker compose up
```

**Right column — usage snippet (Python, since that's the dominant LLM client language):**

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8080/v1",  # ← point at Cascadia
    api_key="anything",                    # ← Cascadia handles upstream auth
)

# That's it. Your existing code keeps working, but now requests are
# routed through the cheapest model that meets your quality bar.
response = client.chat.completions.create(
    model="auto",                          # ← Cascadia picks the tier
    messages=[{"role": "user", "content": "Write a haiku about caching."}],
)
```

**Tone:** "That's it." line is the hook. Existing code, no rewrites, drop-in.

**README adaptation:** Same content; tabs become collapsed `<details>` blocks for non-Docker installs.

---

### 4.5 How it works **[README]**

Section heading: `H2: How it works`.

**Layout:** Centered diagram with explanatory caption below. ~960 px wide, fills the content column.

**Content:** A simplified version of the full architecture diagram from `PLAN.md §3`. Show the three load-bearing flows in different colors:

- **Hot path** (request → proxy → tier → response): `text.primary` lines.
- **Shadow path** (request → proxy → shadow eval): dashed `accent.primary` lines.
- **Learning path** (events → judge → controller → policy update → proxy): dashed `accent.warn` lines.

**Caption (below):**

> Every request enters through the Rust proxy, which routes it to a cheap model first and escalates only if confidence is low. In the background, a slice of decisions is shadow-routed to the expensive tier; a judge worker scores both responses; the policy controller refits per-cluster thresholds. The proxy hot-reloads the new policy. No human in the loop after deployment.

**Link below caption:** `Read the full architecture →` to `docs/ARCHITECTURE.md`.

---

### 4.6 Headline numbers **[README]**

Section heading: `H2: Benchmarks`.

**Layout:** Three big numbers in a row, then a small "how we measured" caption.

```
   78%                97%               <2 ms
   cost reduction     of Sonnet quality routing overhead (P99)
   vs Sonnet-everywhere
```

Each number in display weight, `accent.primary`. Below each: short label + tiny "vs baseline" line in `text.muted`.

**Caption (below, smaller):**

> Measured on a 2,400-prompt blend of MT-Bench, HumanEval, and a redacted LMSys-Chat-1M sample. Judge: 3-model ensemble (Sonnet-3.5, GPT-4o, Gemini-1.5-Pro), calibrated against 200 human-rated examples (Kendall's τ = 0.74). Reproduce: `make bench`.

> ⚠ Phase-0 status: numbers above are *aspirational targets* until Phase 6 ships. The README will switch to measured numbers in green at that point; until then they read in `accent.warn`.

**Why this caveat:** Honesty is a credibility differentiator. Faking numbers ruins the project; clearly distinguishing target-vs-measured is unusual and credibility-positive.

---

### 4.7 Comparison table **[README]**

Section heading: `H2: How Cascadia compares`.

| Capability                                  | Cascadia | LiteLLM | Portkey | RouteLLM | Raw OpenAI |
| ------------------------------------------- | :------: | :-----: | :-----: | :------: | :--------: |
| OpenAI-compatible API                       |    ✓     |    ✓    |    ✓    |    —     |     ✓      |
| Multi-provider routing                      |    ✓     |    ✓    |    ✓    |    ✓     |     —      |
| Static cost-based routing rules             |    ✓     |    ✓    |    ✓    |    ~     |     —      |
| Cascading inference (cheap → expensive)     |    ✓     |    —    |    —    |    ~     |     —      |
| **Learned thresholds from live traffic**    |  **✓**   |    —    |    —    |    —     |     —      |
| **Counterfactual shadow eval**              |  **✓**   |    —    |    —    |    —     |     —      |
| **Per-cluster routing policy**              |  **✓**   |    —    |    —    |    ~     |     —      |
| Self-hostable                               |    ✓     |    ✓    |    ✓    |    ✓     |     —      |
| Open source license                         |   MIT    |   MIT   |  AGPL   |   MIT    |     —      |
| Production-grade observability shipped      |    ✓     |    ~    |    ✓    |    —     |     —      |

**Bolded rows are the three claims** — they are the cells where Cascadia is the only ✓.

**Caption:** "Comparison reflects each tool as of [DATE]. Corrections welcome via PR — see `docs/comparison-methodology.md` for sourcing."

---

### 4.8 Eval methodology callout

**Layout:** Single full-width card with a serious-tone treatment. `bg.surface-2` background.

**Content:**

> **Why trust the numbers?**
>
> Cascadia's whole pitch depends on judging LLM output quality cheaply *and credibly*. We treat the eval methodology as a first-class artifact:
>
> - 3-model judge ensemble (different vendors, different prompt formats) to mitigate self-preference and position bias.
> - Calibration against 200 human-rated examples; we publish the agreement (Kendall's τ) prominently.
> - Continuous re-calibration as judge models drift over time.
> - Every benchmark is reproducible from a single `make bench` command.
>
> [Read the eval methodology →](docs/methodology.md)

**Why this section exists:** Technical reviewers who read papers will look for this. Without it, the headline numbers are unfalsifiable; with it, they're a credibility statement.

---

### 4.9 Footer *(landing only)*

**Layout:** Four columns of small text.

- **Cascadia**: brief tagline + license + version.
- **Docs**: links to Getting started, Architecture, Methodology, Benchmarks, Comparison.
- **Code**: GitHub, crates.io, Helm chart.
- **About**: Blog, Roadmap, Contributing, Contact.

Bottom row: copyright + `Built by Chris King` link + paper references (FrugalGPT, RouteLLM, AutoMix — title and author lines, with `arxiv` links *to be added after URL verification*).

**README equivalent:** A simple `## Related work` section listing the three papers.

---

## 5. Responsive notes

| Breakpoint | Width  | Changes                                                                                                                                                                                              |
| ---------- | ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Desktop    | ≥1024  | Full layout as specified.                                                                                                                                                                            |
| Tablet     | 768–1023 | Hero stacks to single column with chart below copy. Three-claims columns reduce to 2-up then 1-up at narrower widths. Comparison table allows horizontal scroll.                                       |
| Mobile     | <768   | Single column everywhere. Hero chart shrinks to ~340 px wide, becomes the prominent first element above the H1 (visual lead reverses to "show first, tell second"). Comparison table horizontal scroll. |

---

## 6. States

### 6.1 Light / dark

Both supported. Dark is the default — developer audience expects it, and the Pareto chart's `accent.primary` operating-point dot reads more dramatically against a dark canvas. Light mode is a toggle in the top nav; respects `prefers-color-scheme` on first load.

### 6.2 Hover / focus

- Primary CTA: hovered state lightens accent by 8%, no transform.
- Secondary CTA: hovered state adds 1 px inner glow at `accent.primary` at 20% opacity.
- Inline code blocks: hover reveals a copy-icon in top-right corner.
- Comparison table rows: hover background `bg.surface-2`.

### 6.3 Scroll

- Top nav: gains border + backdrop-blur once scrolled past hero (24 px transition zone).
- Pareto chart in hero: parallax-free. No fancy scroll choreography — calm is the point.
- Three-claims columns: subtle stagger fade-in (each card 60ms after previous) on first scroll-into-view. After that, static.

### 6.4 Loading

- Hero chart: skeleton placeholder with dotted axes for ~100 ms, then real chart fades in. Avoids layout shift.
- GitHub star count: shows "—" until API call resolves, then updates.

---

## 7. README adaptation summary

The README is a faithful subset, not a separate design. Rules:

1. **No nav.** GitHub provides its own.
2. **Pareto chart as static SVG** at `docs/assets/pareto-hero.svg`. Center-aligned, max 720 px wide.
3. **No tabs.** Install variants become `<details>` collapsible blocks, Docker open by default.
4. **No animations.** Anywhere.
5. **No comparison-table accent color tricks.** Plain GHFM table.
6. **No footer.** Replaced by a brief "## Related work" + "## License" at the bottom.
7. **Phase-0 banner** at the very top: warning callout that this is early/scaffolding work.

---

## 8. Decisions made in this spec

These decisions should be appended to `PLAN.md` §9 as soon as the spec is approved:

1. **Brand visual direction:** dense-technical-restrained, dark-default, accent teal `#5AE3D6`. Reference adjacent: PostHog, Linear, Modal, Plausible.
2. **Type system:** Inter Tight (display), Inter (body), JetBrains Mono (code).
3. **Landing and README are one design, two renders.** Spec captures both.
4. **Honesty over hype:** Phase-0 benchmark numbers are clearly marked as targets until Phase 6 ships measured numbers.
5. **Footer is landing-only;** README ends at "Related work" + "License."

---

## 9. Open questions (need Chris's input before Figma)

### 9.1 Is the H1 the wordmark or the tagline?

- **Option A:** H1 = "Cascadia." Tagline as subhead. Clean, brand-forward.
- **Option B:** H1 = "Pay 78% less for LLM calls without lowering quality." Wordmark stays smaller above. Benefits-forward, more SaaS-y, higher conversion-energy.
- **Option C:** H1 = "The first LLM gateway that learns from your traffic." Differentiator-forward.

Recommendation: **A** for the evaluator audience (clean, confident, ML-systems-credible). Re-evaluate after Phase 6 if a marketing-style landing makes sense.

### 9.2 Should the Pareto-chart "operating point" be live or canned?

- **Canned demo data** is honest if labeled (e.g., "Demo data, not your traffic").
- **Live data from a public demo deployment** is more impressive but requires a public Cascadia instance, which is post-Phase-6 work.

Recommendation: **Canned with a clear "demo data" inset label** until Phase 6.

### 9.3 What's the canonical GitHub username/org?

Affects every install command, every link, every badge. Need to confirm before Figma renders any final copy. (Likely `cking` or a new `cascadia` org.)

### 9.4 Logo / wordmark

The spec uses "Cascadia" in JetBrains Mono. Is a real logomark needed for now, or does typographic-only wordmark suffice? Recommendation: typographic-only for Phase 0; revisit before public launch.

### 9.5 Should I commission a real artist for any visual element?

Almost certainly not for Phase 0. The Pareto chart is more important than any illustration.

---

## 10. Next actions

1. Chris reviews this spec.
2. Resolve open questions in §9.
3. Append §8 decisions to `PLAN.md` §9 (Decisions log).
4. Take spec into Figma via MCP (`figma-use` + `figma-generate-design` skills mandatory pre-load):
   - Set up file with design tokens, type styles, layout grid.
   - Build the Pareto-frontier chart component first (highest-risk visual).
   - Compose the hero section.
   - Iterate on Chris's feedback.
   - Build remaining sections.
5. Once approved in Figma, generate the static SVG export for the README hero, then move to next view (likely Pareto-frontier dashboard view).
