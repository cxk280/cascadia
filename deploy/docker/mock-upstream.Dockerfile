# Cascadia mock upstream — instant OpenAI-shaped stub provider.
#
# Powers the keyless `npx cascadia demo` stack: the proxy points its cheap +
# expensive tiers at this, and the judge-worker points its scoring client at it
# too (it returns a JSON verdict when it sees a judge prompt). No API keys, no
# cost, fully offline.
#
# Build context: repo root (the workspace Cargo.toml + crates/mock-upstream).
# Usage:
#   docker build -f deploy/docker/mock-upstream.Dockerfile -t cascadia-mock-upstream:local .
#
# Same cargo-chef multi-stage shape as proxy.Dockerfile so dependency layers
# are shared/cached across the two Rust images.

# ---- planner: emit a recipe of all workspace dependencies ----
FROM rust:1.88-bookworm AS planner
WORKDIR /build
RUN cargo install cargo-chef --locked --version 0.1.68
COPY Cargo.toml Cargo.lock rust-toolchain.toml ./
COPY crates ./crates
RUN cargo chef prepare --recipe-path recipe.json

# ---- cacher: build only the dependencies ----
FROM rust:1.88-bookworm AS cacher
WORKDIR /build
RUN cargo install cargo-chef --locked --version 0.1.68
# Pin the same toolchain as the builder (rust-toolchain.toml says
# channel="stable") so cargo-chef's cooked deps are actually reused instead of
# being rebuilt under a newer rustc. Copied AFTER the cargo-chef install so that
# install layer stays cacheable. See proxy.Dockerfile for the full why.
COPY rust-toolchain.toml ./
COPY --from=planner /build/recipe.json recipe.json
RUN cargo chef cook --release --recipe-path recipe.json

# ---- builder: build the mock-upstream binary against the cached deps ----
FROM rust:1.88-bookworm AS builder
WORKDIR /build
COPY --from=cacher /build/target target
COPY --from=cacher /usr/local/cargo /usr/local/cargo
COPY Cargo.toml Cargo.lock rust-toolchain.toml ./
COPY crates ./crates
RUN cargo build --release -p cascadia-mock-upstream
RUN strip target/release/cascadia-mock-upstream

# ---- runtime: distroless, non-root, minimal ----
FROM gcr.io/distroless/cc-debian12:nonroot AS runtime
WORKDIR /app
COPY --from=builder /build/target/release/cascadia-mock-upstream /usr/local/bin/cascadia-mock-upstream

# Listen on all interfaces inside the container so other compose services can
# reach it; override with CASCADIA_MOCK_LISTEN_ADDR.
ENV CASCADIA_MOCK_LISTEN_ADDR=0.0.0.0:18081
EXPOSE 18081

USER nonroot:nonroot
ENTRYPOINT ["/usr/local/bin/cascadia-mock-upstream"]
