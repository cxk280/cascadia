# Cascadia dashboard — Next.js 14 (app router) operator UI.
#
# Build context: repo root.
# Usage:
#   docker build -f deploy/docker/dashboard.Dockerfile -t cascadia-dashboard:dev .
#
# Multi-stage: deps -> builder -> runtime, using Next.js `output: "standalone"`
# so the runtime image only ships the pruned server bundle + static assets.

# ---- deps: cached npm install ----
FROM node:20-bookworm-slim AS deps
WORKDIR /app
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci --no-audit --no-fund

# ---- builder: compile Next.js standalone bundle ----
FROM node:20-bookworm-slim AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY dashboard/ ./
RUN npm run build

# ---- runtime: distroless node, non-root, minimal ----
FROM gcr.io/distroless/nodejs20-debian12:nonroot AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# The standalone build emits server.js + minimal node_modules at
# .next/standalone, plus a sibling .next/static and public/ that we copy in
# alongside. Owners are set to nonroot (uid 65532) so the distroless runtime
# can read them.
COPY --from=builder --chown=nonroot:nonroot /app/.next/standalone ./
COPY --from=builder --chown=nonroot:nonroot /app/.next/static ./.next/static
COPY --from=builder --chown=nonroot:nonroot /app/public ./public

EXPOSE 3000

# Runtime env vars expected (set on Railway):
#   CASCADIA_DASHBOARD_API_BASE   - e.g. http://dashboard-api.railway.internal:8080
#   CASCADIA_CALIBRATE_USER       - HTTP basic-auth user for /calibrate (defaults "cascadia")
#   CASCADIA_CALIBRATE_PASS       - HTTP basic-auth pass (required in production)
USER nonroot:nonroot
ENTRYPOINT ["/nodejs/bin/node", "server.js"]
