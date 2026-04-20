#!/usr/bin/env bash
# scripts/bootstrap_env.sh — idempotent .env initialiser for Hive v0.
#
# Usage:
#   bash scripts/bootstrap_env.sh
#
# What it does:
#   - If .env does not exist at the repo root, copies .env.example → .env.
#   - If .env already exists, does nothing (idempotent).
#
# NOTE: This script must be executable. Run once after cloning:
#   chmod +x scripts/bootstrap_env.sh
#
set -euo pipefail

# Resolve repo root regardless of the working directory from which the script
# is invoked (follows symlinks via readlink -f).
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
REPO_ROOT="${SCRIPT_DIR}/.."

ENV_FILE="${REPO_ROOT}/.env"
EXAMPLE_FILE="${REPO_ROOT}/.env.example"

if [ ! -f "${ENV_FILE}" ]; then
    if [ ! -f "${EXAMPLE_FILE}" ]; then
        echo "ERROR: ${EXAMPLE_FILE} not found. Repository may be incomplete." >&2
        exit 1
    fi
    cp "${EXAMPLE_FILE}" "${ENV_FILE}"
    echo "Created .env from .env.example — fill in secrets before running \`hive up\`."
else
    echo ".env already exists — leaving in place."
fi

exit 0
