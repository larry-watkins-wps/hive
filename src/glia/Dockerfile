# src/glia/Dockerfile — Hive infrastructure container (spec §E.1, §E.2; plan 5.1).
#
# Build from repo root:
#   docker build -t hive-glia:v0 -f src/glia/Dockerfile .
#
# Runtime mounts (configured in docker-compose.yaml — plan 6.1):
#   /var/run/docker.sock   Docker socket (RW; bind-mounted from host so the
#                          docker SDK can manage region containers at runtime)
#   /hive/regions/         Per-region state dirs (RW; bind-mounted host volume)
#
# Glia has no LLM. It uses only: docker SDK, aiomqtt, jinja2, ruamel.yaml,
# structlog, and prometheus-client.

# python:3.11-slim-bookworm pinned by digest (reproducible builds). Same base
# as region_template/Dockerfile — bump both together when upstream publishes a
# security update.
FROM python:3.11-slim-bookworm@sha256:9c6f90801e6b68e772b7c0ca74260cbf7af9f320acec894e26fccdaccfbe3b47

# System deps:
#   git   — required for rollback (spec §E.5): glia runs `git revert` inside
#            bind-mounted regions/<name>/ directories on the host.
#   tini  — signal forwarding + zombie reaping (SIGTERM propagation to python).
RUN apt-get update \
 && apt-get install -y --no-install-recommends git tini \
 && rm -rf /var/lib/apt/lists/*

# Non-root user (spec §J.1.2). UID 1000 matches the typical developer UID used
# in host bind-mount docs so volume ownership lines up without chown.
ARG HIVE_UID=1000
ARG HIVE_GID=1000
RUN groupadd --system --gid ${HIVE_GID} hive \
 && useradd --system --uid ${HIVE_UID} --gid hive \
      --create-home --home-dir /home/hive --shell /usr/sbin/nologin hive

# PYTHONDONTWRITEBYTECODE — avoids writing .pyc into bind-mounted dirs.
# PYTHONUNBUFFERED      — line-buffered stdout for docker logs JSON pickup (§H.1).
# PYTHONPATH            — /hive/shared and /hive/bus import directly without
#                         an editable pip install.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/hive

WORKDIR /hive

# Runtime deps mirror glia/pyproject.toml — keep these two lists in sync.
# NOTE: docker SDK (docker>=7) communicates with the Docker daemon via
# /var/run/docker.sock (bind-mounted at runtime — see docker-compose.yaml).
# The docker CLI binary is NOT installed; the Python SDK is sufficient.
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir \
      "docker>=7" \
      "jinja2" \
      "aiomqtt>=2.0,<3" \
      "ruamel.yaml" \
      "structlog>=24" \
      "prometheus-client" \
      "jsonschema>=4.20" \
      "pydantic>=2.6"

# Copy glia source and shared utilities. At runtime docker-compose bind-mounts
# the host directories over these paths for live reload during development.
COPY --chown=hive:hive src/shared/ /hive/shared/
COPY --chown=hive:hive bus/ /hive/bus/
COPY --chown=hive:hive src/glia/ /hive/glia/

USER hive

# tini handles signal forwarding and reaps any zombie subprocesses.
ENTRYPOINT ["/usr/bin/tini", "--", "python", "-m", "glia"]
