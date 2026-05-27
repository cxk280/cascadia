# Cascadia proxy — Rust hot-path service.
#
# Build context: repo root (the workspace Cargo.toml + crates/proxy + crates/mock-upstream).
# Usage:
#   docker build -f deploy/docker/proxy.Dockerfile -t cascadia-proxy:dev .
#
# Multi-stage. Stage 1 caches the workspace dependency graph via cargo-chef so
# the slow `cargo build --release` only re-runs when Cargo.{toml,lock} change.
# Stage 2 is a distroless runtime — no shell, no apt, ~25 MB final image.

# ---- planner: emit a recipe of all workspace dependencies ----
FROM rust:1.88-bookworm AS planner
WORKDIR /build
RUN cargo install cargo-chef --locked --version 0.1.68
COPY Cargo.toml Cargo.lock rust-toolchain.toml ./
COPY crates ./crates
RUN cargo chef prepare --recipe-path recipe.json

# ---- cacher: build only the dependencies (huge layer, rarely invalidated) ----
FROM rust:1.88-bookworm AS cacher
WORKDIR /build
RUN cargo install cargo-chef --locked --version 0.1.68
COPY --from=planner /build/recipe.json recipe.json
RUN cargo chef cook --release --recipe-path recipe.json

# ---- builder: build the proxy binary against the cached deps ----
FROM rust:1.88-bookworm AS builder
WORKDIR /build
COPY --from=cacher /build/target target
COPY --from=cacher /usr/local/cargo /usr/local/cargo
COPY Cargo.toml Cargo.lock rust-toolchain.toml ./
COPY crates ./crates
RUN cargo build --release -p cascadia-proxy
RUN strip target/release/cascadia-proxy

# ---- runtime: distroless, non-root, minimal ----
FROM gcr.io/distroless/cc-debian12:nonroot AS runtime
WORKDIR /app

# Migrations are read at proxy startup via sqlx::migrate!() embedded in the
# binary — no need to copy migrations/ into the runtime image. The proxy
# embeds them via include_dir!() at build time.
COPY --from=builder /build/target/release/cascadia-proxy /usr/local/bin/cascadia-proxy

# Default listen addr is 0.0.0.0:8080 (overrideable via CASCADIA_LISTEN_ADDR).
EXPOSE 8080

USER nonroot:nonroot
ENTRYPOINT ["/usr/local/bin/cascadia-proxy"]
