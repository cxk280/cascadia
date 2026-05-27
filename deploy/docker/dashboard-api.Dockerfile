# Cascadia dashboard-api — FastAPI read-side over Postgres.
#
# Build context: repo root.
# Usage:
#   docker build -f deploy/docker/dashboard-api.Dockerfile -t cascadia-dashboard-api:dev .
#
# Two-stage: builder installs into a venv at /opt/venv, runtime copies the venv
# into a slim image and runs as a non-root user.

# ---- builder ----
FROM python:3.12-slim-bookworm AS builder
WORKDIR /build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

# Build wheels into a venv that we copy verbatim into the runtime stage.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy only the service so the build cache doesn't invalidate on unrelated
# repo changes.
COPY services/dashboard-api/pyproject.toml services/dashboard-api/README.md ./
COPY services/dashboard-api/cascadia_dashboard ./cascadia_dashboard

RUN pip install --upgrade pip && pip install .

# ---- runtime ----
FROM python:3.12-slim-bookworm AS runtime
WORKDIR /app
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CASCADIA_DASHBOARD_HOST=0.0.0.0 \
    CASCADIA_DASHBOARD_PORT=8080

COPY --from=builder /opt/venv /opt/venv

# Ship the calibration rubric next to the dashboard-api so the /api/calibrate/
# rubric endpoint resolves it at runtime. The judge-worker also reads this
# file but lives in its own image; we ship a copy here rather than mounting
# a shared volume across services. Updates to the rubric require a rebuild
# — intentional, since the rubric is part of the methodology contract.
COPY services/judge-worker/calibration/rubric_v2.md /app/calibration/rubric_v2.md
ENV CASCADIA_RUBRIC_PATH=/app/calibration/rubric_v2.md

# Non-root runtime user (uid 1000). FastAPI/uvicorn need nothing else from the FS.
RUN useradd --create-home --uid 1000 cascadia
USER cascadia

EXPOSE 8080

# Uvicorn entrypoint. Reads CASCADIA_DATABASE_URL, CASCADIA_DASHBOARD_CORS_ORIGINS
# from the env. `cascadia-dashboard-api` is installed as a console script by hatch.
ENTRYPOINT ["cascadia-dashboard-api"]
