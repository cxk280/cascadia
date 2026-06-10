# Releasing Cascadia

This is the runbook for shipping a release to end users. Two artifacts move together:

1. **The npm launcher** — `cascadia-gateway` (`cli/`). This is what `npx cascadia-gateway` runs.
2. **The GHCR images** — `ghcr.io/cxk280/cascadia-*`, which the launcher pulls. The launcher pins them by its own version: `PUBLISHED_IMAGE_TAG = v${cli/package.json.version}` (`cli/lib/commands.js`). So **launcher `x.y.z` pulls `vx.y.z` images** — the npm version and the git tag must match, and CI enforces it.

> **Two steps are the maintainer's alone and must never be automated:** merging the `v2 → main` PR, and `npm publish`. Everything else is scripted/CI.

## What's auto vs. manual

- **Live Railway deploys** (dev/staging/prod) rebuild from source on each deploy — merging to `main` auto-deploys dev, then staging/prod are behind manual CircleCI approval gates. Not part of the npm release; happens on the merge.
- **Moving edge images** (`:edge` from `main`, `:v2` from `v2`) are published automatically on merge — for testing latest code via `CASCADIA_TAG=edge`. **Not** a release.
- **Pinned release images** (`:vX.Y.Z` + `:latest`) and the **npm package** only move on a deliberate `v*` tag + `npm publish` — this runbook.

## Release steps (in order)

### 0. Pre-flight
- [ ] `v2` CI is green (the v2 edge build + tests pass).
- [ ] `cli/package.json` `version` is the version you intend to release (e.g. `1.0.0`), and it matches the tag you'll cut in step 3. (This release-prep PR sets it.)
- [ ] `make verify` is green locally.

### 1. Merge `v2 → main`  *(maintainer only)*
Open a PR `v2 → main`, review the accumulated feature set, and merge it.
- This **auto-deploys `dev`** (CircleCI `deploy-dev`); approve the `hold-staging` then `hold-prod` gates in CircleCI when you want the live envs to advance.
- After this merge, `main` merges publish `:edge` images automatically.

### 2. Confirm the version on `main`
- [ ] On `main`, `cli/package.json` `version` == the version you're releasing. (It rode in with the v2 merge.)

### 3. Cut + push the release tag  →  CI builds the images
```bash
git checkout main && git pull
VERSION="v$(node -p "require('./cli/package.json').version")"   # e.g. v1.0.0
git tag "$VERSION" && git push origin "$VERSION"
```
This triggers the tag pipeline: native `build-amd64` + `build-arm64` (no QEMU) → `merge-manifests` pushes multi-arch `:$VERSION` + `:latest` to GHCR. **≈ 40 min.**
- The `launcher` CI job **fails the build if `CIRCLE_TAG` ≠ `v$(cli version)`** — so a mismatched tag/version can't ship.
- [ ] Wait for the tag pipeline to go **green** before publishing.
- [ ] (First release of a new image only) ensure the GHCR package visibility is **Public**.

### 4. Publish the launcher to npm  *(maintainer only)*
```bash
cd cli && npm publish
```
`prepack` re-syncs the bundled `cli/assets/docker-compose.demo.yml` from `deploy/compose/` automatically. **Order matters — the images (step 3) must exist before the launcher that pins them ships.**

### 5. Verify
```bash
npx cascadia-gateway@latest demo     # pulls :v<version> images, brings up the keyless demo
```
- [ ] The demo comes up and the dashboard loads.
- [ ] `npx cascadia-gateway@latest version` prints the new version.

## Rollback / fixups
- **Bad images, not yet published to npm:** delete the tag (`git push origin :vX.Y.Z`) + the GHCR image versions, fix, re-tag. (Pruning GHCR versions needs a token with `delete:packages`.)
- **Already `npm publish`ed:** npm versions are immutable — bump to the next patch and re-release rather than unpublishing. `:latest` will move to the new patch on its tag build.
- Validate any CI pipeline change with a throwaway `vX.Y.Z-rc.N` tag first, then delete the rc tag + its rc images.

## Quick reference
| Action | Trigger | Result |
|---|---|---|
| merge → `main` | maintainer | deploy dev (auto) + staging/prod (gated); `:edge` images |
| merge → `v2` | PR | deploy v2 preview; `:v2` images |
| push `vX.Y.Z` tag | maintainer | build + push `:vX.Y.Z` + `:latest` images (~40 min) |
| `npm publish` | maintainer | `cascadia-gateway@X.Y.Z` live; `npx` users get it |
