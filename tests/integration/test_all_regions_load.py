"""Integration test: verify all 14 scaffolded regions load without error.

Task 8.15 — spec §F.5 (config), §A.6.3 (handler discovery).

Checks (per region, parametrized):
  1. ``config_loader.load_config`` parses config.yaml and returns a
     ``RegionConfig`` whose ``.name`` matches the directory name.
  2. ``handlers_loader.discover`` on the handlers/ directory returns an
     empty list (no handlers in the scaffolded stubs).
  3. ``prompt.md`` exists and is non-empty.

Additionally, a single non-parametrized test asserts the region set on-disk
matches the expected 14 exactly (guards against future drift).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from region_template import config_loader, handlers_loader

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REGIONS_DIR = _REPO_ROOT / "regions"

_EXPECTED_REGIONS = [
    "amygdala",
    "anterior_cingulate",
    "association_cortex",
    "auditory_cortex",
    "basal_ganglia",
    "broca_area",
    "hippocampus",
    "insula",
    "medial_prefrontal_cortex",
    "motor_cortex",
    "prefrontal_cortex",
    "thalamus",
    "visual_cortex",
    "vta",
]


# ---------------------------------------------------------------------------
# Filesystem-completeness guard (non-parametrized)
# ---------------------------------------------------------------------------


def test_region_set_matches_expected() -> None:
    """The regions/ directory must contain exactly the 14 expected regions."""
    on_disk = sorted(p.name for p in _REGIONS_DIR.iterdir() if p.is_dir())
    assert on_disk == _EXPECTED_REGIONS, (
        f"Region set mismatch.\n"
        f"  Expected : {_EXPECTED_REGIONS}\n"
        f"  On disk  : {on_disk}"
    )


# ---------------------------------------------------------------------------
# Per-region parametrized assertions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("region_name", _EXPECTED_REGIONS)
def test_region_loads(region_name: str) -> None:
    """Each region's config, handlers, and prompt must load correctly."""
    region_dir = _REGIONS_DIR / region_name

    # --- 1. config.yaml loads and .name matches the directory name -----------
    cfg = config_loader.load_config(region_dir / "config.yaml")
    assert cfg.name == region_name, (
        f"{region_name}: config.name={cfg.name!r} != directory name"
    )

    # --- 2. handlers/ discovery returns empty list ---------------------------
    handlers = handlers_loader.discover(region_dir / "handlers")
    assert len(handlers) == 0, (
        f"{region_name}: expected 0 handlers in scaffold, got {len(handlers)}: "
        + ", ".join(h.name for h in handlers)
    )

    # --- 3. prompt.md exists and is non-empty --------------------------------
    prompt_path = region_dir / "prompt.md"
    assert prompt_path.exists(), f"{region_name}: prompt.md not found at {prompt_path}"
    assert prompt_path.stat().st_size > 0, f"{region_name}: prompt.md is empty"
