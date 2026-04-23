# region_template/Dockerfile — shared image for all Hive regions (spec §0.5, §G.7; plan 4.1).
#
# Build from repo root:
#   docker build -t hive-region:v0 -f region_template/Dockerfile .
#
# Runtime layout (bind-mounted by glia at container launch — spec §0.5, §G.7):
#   /hive/region/          region state dir (RW; per-region host volume)
#   /hive/region_template/ DNA (RO; replaced from host for hot-reload)
#   /hive/shared/          shared utilities (RO; replaced from host)
#
# Region identity: $HIVE_REGION selects the config path — see
# region_template/__main__.py:_resolve_env_config.

# python:3.11-slim-bookworm pinned by digest (reproducible builds). Bump when
# upstream publishes a security update and update scripts/setup.sh if the
# minor version changes.
FROM python:3.11-slim-bookworm@sha256:9c6f90801e6b68e772b7c0ca74260cbf7af9f320acec894e26fccdaccfbe3b47

# System deps: git is required by region_template/git_tools.py (subprocess).
# tini reaps zombies when the runtime spawns the sleep-pipeline compile
# subprocess. ca-certificates is already present in python:slim.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git tini \
 && rm -rf /var/lib/apt/lists/*

# Non-root user (P-III; spec §J.1.2). UID 1000 matches the convention used
# in the host bind-mount docs so the baked /hive/region_template owner lines
# up with the typical developer UID.
ARG HIVE_UID=1000
ARG HIVE_GID=1000
RUN groupadd --system --gid ${HIVE_GID} hive \
 && useradd --system --uid ${HIVE_UID} --gid hive \
      --create-home --home-dir /home/hive --shell /usr/sbin/nologin hive

# PYTHONDONTWRITEBYTECODE — sleep pipeline hygiene (spec §D.5; avoids writing
#   .pyc into bind-mounted region_template/ at runtime).
# PYTHONUNBUFFERED — line-buffered stdout for docker logs JSON pickup (§H.1).
# PYTHONPATH — flat-layout fallback: /hive/shared and /hive/region_template
#   import directly without an editable pip install. See CLAUDE.md "flat
#   layout" note.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/hive

WORKDIR /hive

# Runtime deps mirror region_template/pyproject.toml and scripts/setup.sh —
# keep these three lists in sync. Pinned only where pyproject pins.
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir \
      "aiomqtt>=2.0,<3" \
      "litellm>=1.54,<2" \
      "ruamel.yaml" \
      "structlog>=24" \
      "jsonschema>=4.20" \
      "pydantic>=2.6" \
      "GitPython>=3.1"

# Copy DNA and shared code. At runtime glia bind-mounts the host directories
# read-only over these paths (spec §0.5); the baked copies serve standalone
# `docker run --rm hive-region:v0 --help` and act as a fallback.
COPY --chown=hive:hive shared/ /hive/shared/
COPY --chown=hive:hive region_template/ /hive/region_template/

USER hive

# tini handles signal forwarding + reaps zombie compile subprocesses.
ENTRYPOINT ["/usr/bin/tini", "--", "python", "-m", "region_template"]
