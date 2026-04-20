#!/usr/bin/env bash
# scripts/setup.sh — one-shot new-machine setup for Hive.
#
# Usage (from repo root):
#   bash scripts/setup.sh
#
# What it does:
#   1. Creates .venv/ (if absent).
#   2. Installs external runtime + dev dependencies into the venv.
#   3. Copies .env.example → .env (via bootstrap_env.sh) if .env is absent.
#   4. Prints the next-step hint.
#
# Note: the local `shared/` and `region_template/` packages are NOT
# pip-installed — the repo uses a flat layout and tests resolve imports
# via conftest.py's sys.path munging. The Phase 4 Dockerfile task will
# introduce a proper installable layout.
#
# Idempotent — safe to re-run.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

PYTHON="${PYTHON:-python}"
VENV_DIR="${REPO_ROOT}/.venv"

# ---- 1. venv ---------------------------------------------------------------
if [ ! -d "${VENV_DIR}" ]; then
    echo "==> Creating .venv with ${PYTHON}..."
    "${PYTHON}" -m venv "${VENV_DIR}"
else
    echo "==> .venv already exists; reusing."
fi

# Locate the venv Python — cross-platform (POSIX vs Git Bash on Windows).
if [ -x "${VENV_DIR}/bin/python" ]; then
    VENV_PY="${VENV_DIR}/bin/python"
elif [ -x "${VENV_DIR}/Scripts/python.exe" ]; then
    VENV_PY="${VENV_DIR}/Scripts/python.exe"
else
    echo "ERROR: cannot locate venv Python in ${VENV_DIR}" >&2
    exit 1
fi

# ---- 2. deps ---------------------------------------------------------------
# Dependency list mirrors region_template/pyproject.toml — kept in sync
# by eye. Phase 4 Dockerfile work will replace this with a proper
# pyproject-driven install.
echo "==> Upgrading pip..."
"${VENV_PY}" -m pip install --quiet --upgrade pip

echo "==> Installing runtime + dev dependencies..."
"${VENV_PY}" -m pip install --quiet \
    "aiomqtt>=2.0,<3" \
    "litellm>=1.54,<2" \
    "ruamel.yaml" \
    "structlog>=24" \
    "jsonschema>=4.20" \
    "pydantic>=2.6" \
    "GitPython>=3.1" \
    "pytest" \
    "pytest-asyncio" \
    "testcontainers>=4" \
    "ruff"

# ---- 3. .env ---------------------------------------------------------------
bash "${SCRIPT_DIR}/bootstrap_env.sh"

# ---- 4. next-step hint -----------------------------------------------------
cat <<EOF

==> Setup complete.

Next steps:
  1. Activate the venv:
       source .venv/bin/activate            # POSIX / Git Bash
       .venv\\Scripts\\activate              # Windows cmd.exe / PowerShell
  2. Edit .env and fill in ANTHROPIC_API_KEY (at minimum).
  3. Run the unit suite to verify:
       python -m pytest tests/unit/ -q      # expect 508 passed
  4. If Docker Desktop is running, run the component suite too:
       python -m pytest tests/component/ -m component -v
  5. Open Claude Code in this directory and say "continue phase 4"
     (or whichever phase). See CLAUDE.md and docs/HANDOFF.md.
EOF
