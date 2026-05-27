# Cascadia policy-controller — periodic refit of per-cluster cascade thresholds.
#
# Build context: repo root.
# Usage:
#   docker build -f deploy/docker/policy-controller.Dockerfile -t cascadia-policy-controller:dev .

# ---- builder ----
FROM python:3.12-slim-bookworm AS builder
WORKDIR /build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY services/policy-controller/pyproject.toml services/policy-controller/README.md ./
COPY services/policy-controller/cascadia_policy ./cascadia_policy

RUN pip install --upgrade pip && pip install .

# ---- runtime ----
FROM python:3.12-slim-bookworm AS runtime
WORKDIR /app
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=builder /opt/venv /opt/venv

RUN useradd --create-home --uid 1000 cascadia
USER cascadia

# Default: long-running refit loop. The CLI re-reads CASCADIA_DATABASE_URL,
# CASCADIA_POLICY_FILE, CASCADIA_LOOKBACK_MINUTES, CASCADIA_REFIT_INTERVAL_SEC
# from the env. The policy file is the rendezvous artifact with the proxy
# (proxy hot-reloads it via arc-swap on inotify) — on Railway this becomes
# a shared volume between the proxy and policy-controller services, or
# emitted to an object store. See deploy README for the wiring choice.
ENTRYPOINT ["cascadia-policy-controller"]
