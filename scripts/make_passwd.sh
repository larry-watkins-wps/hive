#!/usr/bin/env bash
# scripts/make_passwd.sh — regenerate bus/passwd from MQTT_PASSWORD_* env vars.
#
# Usage:
#   bash scripts/make_passwd.sh
#
# What it does:
#   1. Sources .env from the repo root (fail with a clear error if missing).
#   2. Removes any existing bus/passwd so this is a full regenerate (not append).
#   3. For each of the 14 brain regions + glia, reads MQTT_PASSWORD_<REGION>
#      and calls mosquitto_passwd to write an entry with username = lowercase
#      region name (e.g. MQTT_PASSWORD_PREFRONTAL_CORTEX → "prefrontal_cortex").
#
# Requires mosquitto_passwd on PATH — see spec §B.8.
#
# NOTE: This script must be executable. Run once after cloning:
#   chmod +x scripts/make_passwd.sh
#
set -euo pipefail

# Resolve repo root regardless of cwd.
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
REPO_ROOT="${SCRIPT_DIR}/.."

ENV_FILE="${REPO_ROOT}/.env"
PASSWD_FILE="${REPO_ROOT}/bus/passwd"

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

if [ ! -f "${ENV_FILE}" ]; then
    echo "ERROR: ${ENV_FILE} not found." >&2
    echo "Run scripts/bootstrap_env.sh first and fill in secrets." >&2
    exit 1
fi

if ! command -v mosquitto_passwd &>/dev/null; then
    echo "ERROR: mosquitto_passwd not found on PATH." >&2
    echo "Install mosquitto-clients (e.g. apt install mosquitto-clients) — see spec §B.8." >&2
    exit 1
fi

# Source .env; allow vars that are unset/empty (we validate below per entry).
set -o allexport
# shellcheck source=../.env
source "${ENV_FILE}"
set +o allexport

# ---------------------------------------------------------------------------
# Ordered list of all regions + glia (uppercase → env var suffix)
# ---------------------------------------------------------------------------

REGIONS=(
    MEDIAL_PREFRONTAL_CORTEX
    PREFRONTAL_CORTEX
    ANTERIOR_CINGULATE
    HIPPOCAMPUS
    THALAMUS
    ASSOCIATION_CORTEX
    INSULA
    BASAL_GANGLIA
    VISUAL_CORTEX
    AUDITORY_CORTEX
    MOTOR_CORTEX
    BROCA_AREA
    AMYGDALA
    VTA
    GLIA
)

# ---------------------------------------------------------------------------
# Validate that all required passwords are set before touching the passwd file
# ---------------------------------------------------------------------------

missing=0
for region in "${REGIONS[@]}"; do
    var="MQTT_PASSWORD_${region}"
    # Use indirect expansion; treat empty string as missing.
    value="${!var:-}"
    if [ -z "${value}" ]; then
        echo "ERROR: ${var} is not set or empty in ${ENV_FILE}." >&2
        missing=1
    fi
done

if [ "${missing}" -eq 1 ]; then
    echo "Aborting — fill in all MQTT_PASSWORD_* entries in .env first." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Rebuild bus/passwd from scratch
# ---------------------------------------------------------------------------

# Ensure the bus/ directory exists (it may not yet in a fresh clone).
mkdir -p "${REPO_ROOT}/bus"

# Remove existing passwd so mosquitto_passwd -b writes fresh entries.
rm -f "${PASSWD_FILE}"

for region in "${REGIONS[@]}"; do
    # Username is the lowercase version of the region name.
    username="${region,,}"
    var="MQTT_PASSWORD_${region}"
    password="${!var}"
    mosquitto_passwd -b "${PASSWD_FILE}" "${username}" "${password}"
done

echo "bus/passwd regenerated with ${#REGIONS[@]} entries."

exit 0
