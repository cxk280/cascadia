<!-- Thanks for opening a PR! See CONTRIBUTING.md for the short version. -->

## What changes

<!-- One paragraph. What does this PR do? -->

## Why

<!-- Link the issue, the PLAN.md §9 decision, or the methodology blog
     section that motivated this. -->

## How

<!-- Brief sketch of the approach. If you considered alternatives, name them. -->

## Test plan

<!-- Concrete commands the reviewer can run. Example:

  cargo test -p cascadia-proxy
  cd services/judge-worker && uv run pytest tests/test_aggregation.py
  curl http://localhost:8080/v1/chat/completions -d '{"model":"auto", ...}'
-->

## Risk + rollback

<!-- What blast radius does this carry? How do you back it out if it
     breaks something? Mark N/A for docs-only changes. -->

## Checklist

- [ ] Added tests at the layer of the change.
- [ ] `cargo clippy --workspace --all-targets -- -D warnings` clean.
- [ ] `ruff check .` clean across touched Python services.
- [ ] `npx tsc --noEmit` clean for dashboard changes.
- [ ] PLAN.md updated if this touches a §9-locked decision.
- [ ] README acceptance table updated if this changes a phase status.
