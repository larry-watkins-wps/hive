# Multi-stage: build frontend, then runtime image.
#
# Build from the repo root:
#   docker build -f observatory/Dockerfile -t observatory:v3 .
#
# Or via docker-compose (which also starts mosquitto):
#   docker compose -f observatory/docker-compose.yml up
#
# Environment knobs (see observatory/config.py):
#   OBSERVATORY_BIND_HOST     default 0.0.0.0 in-container
#   OBSERVATORY_BIND_PORT     default 8765
#   OBSERVATORY_MQTT_URL      default mqtt://mosquitto:1883 in-container
#   OBSERVATORY_REGIONS_ROOT  default /hive/regions (mount read-only)
#   OBSERVATORY_HIVE_REPO_ROOT default /hive (mount read-only for glia/regions_registry.yaml)

FROM node:20-alpine AS frontend
WORKDIR /src
# Cache npm install layer by copying manifests first.
COPY observatory/web-src/package.json observatory/web-src/package-lock.json* ./
RUN npm ci
COPY observatory/web-src/ ./
# vite config outDir is `../web` relative to web-src, i.e. /web inside this stage.
RUN npm run build

FROM python:3.11-slim AS runtime
WORKDIR /app

# Install runtime deps first so this layer caches unless deps change. The deps
# list is duplicated from observatory/pyproject.toml's [project.dependencies]
# — keep in sync. We skip the flit install path (would need the full source
# tree to build a wheel) and run the package directly via PYTHONPATH.
RUN pip install --no-cache-dir \
  "fastapi>=0.110" \
  "uvicorn[standard]>=0.27" \
  "aiomqtt>=2.0,<3" \
  "pydantic>=2.6" \
  "structlog>=24" \
  "ruamel.yaml"

# Copy observatory source + built frontend bundle.
COPY observatory/ ./observatory/
COPY --from=frontend /web ./observatory/web

# Drop the dev-only web-src/ and tests/ from the runtime image. The fresh
# frontend bundle at ./observatory/web is what FastAPI's static mount serves.
RUN rm -rf ./observatory/web-src ./observatory/tests

ENV PYTHONPATH=/app
ENV OBSERVATORY_BIND_HOST=0.0.0.0
ENV OBSERVATORY_BIND_PORT=8765
ENV OBSERVATORY_MQTT_URL=mqtt://mosquitto:1883

EXPOSE 8765

# Simple liveness probe: FastAPI /api/health returns {status:"ok",version:...}.
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request, sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=2).status == 200 else 1)"

CMD ["python", "-m", "observatory"]
