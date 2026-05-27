# Cascadia judge-worker — polls shadow_pairs, calls LLM judges, writes judge_scores.
#
# Build context: repo root.
# Usage:
#   docker build -f deploy/docker/judge-worker.Dockerfile -t cascadia-judge-worker:dev .
#
# Default ENTRYPOINT is the polling worker (`cascadia-judge-poll`). To run the
# calibration CLI etc., override the entrypoint at `docker run`/Railway level.

# ---- builder ----
FROM python:3.12-slim-bookworm AS builder
WORKDIR /build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY services/judge-worker/pyproject.toml services/judge-worker/README.md ./
COPY services/judge-worker/cascadia_judge ./cascadia_judge

RUN pip install --upgrade pip && pip install .

# ---- runtime ----
FROM python:3.12-slim-bookworm AS runtime
WORKDIR /app
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=builder /opt/venv /opt/venv

# Include the calibration rubric so calibration-related CLIs invoked from this
# image can find their config without a separate mount.
COPY services/judge-worker/calibration /opt/cascadia-judge/calibration

RUN useradd --create-home --uid 1000 cascadia
USER cascadia

# Default: continuous poll over shadow_pairs. Reads CASCADIA_DATABASE_URL and
# the relevant *_API_KEY env vars (OPENAI_API_KEY, ANTHROPIC_API_KEY, GROQ_API_KEY)
# per the panel config. Override entrypoint to run other CLIs from this image:
#   docker run --entrypoint cascadia-judge-calibrate cascadia-judge-worker:dev …
ENTRYPOINT ["cascadia-judge-poll"]
