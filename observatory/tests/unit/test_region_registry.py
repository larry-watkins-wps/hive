"""Region registry invariants."""
from __future__ import annotations

from pathlib import Path

import pytest

from observatory.region_registry import RegionRegistry

REGISTRY_YAML = """\
regions:
  - name: thalamus
    role: cognitive
    llm_model: claude-opus-4-6
  - name: amygdala
    role: modulatory
    llm_model: claude-haiku-4-5
"""


@pytest.fixture
def seeded(tmp_path: Path) -> RegionRegistry:
    glia_dir = tmp_path / "glia"
    glia_dir.mkdir()
    (glia_dir / "regions_registry.yaml").write_text(REGISTRY_YAML, encoding="utf-8")
    return RegionRegistry.seed_from(tmp_path)


def test_seed_loads_names_and_roles(seeded: RegionRegistry) -> None:
    names = sorted(seeded.names())
    assert names == ["amygdala", "thalamus"]
    assert seeded.get("thalamus").role == "cognitive"
    assert seeded.get("amygdala").llm_model == "claude-haiku-4-5"


def test_heartbeat_updates_stats(seeded: RegionRegistry) -> None:
    seeded.apply_heartbeat("thalamus", {
        "status": "wake",
        "phase": "wake",
        "queue_depth_messages": 3,
        "stm_bytes": 1024,
        "llm_tokens_used_lifetime": 500,
        "handler_count": 4,
        "last_error_ts": None,
    })
    stats = seeded.get("thalamus").stats
    assert stats.phase == "wake"
    assert stats.queue_depth == 3  # noqa: PLR2004
    assert stats.stm_bytes == 1024  # noqa: PLR2004
    assert stats.tokens_lifetime == 500  # noqa: PLR2004


def test_heartbeat_from_unknown_region_registers_it(seeded: RegionRegistry) -> None:
    seeded.apply_heartbeat("hippocampus", {
        "status": "wake", "phase": "wake",
        "queue_depth_messages": 0, "stm_bytes": 0,
        "llm_tokens_used_lifetime": 0, "handler_count": 0,
        "last_error_ts": None,
    })
    assert "hippocampus" in seeded.names()
    # role is empty when auto-registered
    assert seeded.get("hippocampus").role == ""


def test_missing_registry_yaml_is_not_fatal(tmp_path: Path) -> None:
    reg = RegionRegistry.seed_from(tmp_path)
    assert reg.names() == []
