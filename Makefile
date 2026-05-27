# Cascadia operator + CI helpers. The actual recipe logic lives in
# scripts/*.sh so it's runnable both via `make <target>` and directly via
# `scripts/<target>.sh` — handy in CI environments without GNU make 4+.

.PHONY: build
build:
	cargo build --release -p cascadia-proxy -p cascadia-mock-upstream

.PHONY: test
test:
	cargo test --workspace

.PHONY: clippy
clippy:
	cargo clippy --workspace --all-targets -- -D warnings

# Verify the OpenAI adapter refuses to dial non-OpenAI hosts (Anthropic,
# Gemini, AWS Bedrock) — Phase 7 footgun protection. No real key required.
.PHONY: test-footgun
test-footgun:
	./scripts/test-footgun.sh

# Verify /readyz emits both passed_checks and failed_checks consistently.
.PHONY: test-readyz
test-readyz:
	./scripts/test-readyz.sh

.PHONY: verify
verify: test test-footgun test-readyz
	@echo "All verification targets passed."
