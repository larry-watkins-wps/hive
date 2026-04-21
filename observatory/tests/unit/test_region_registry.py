"""Region registry invariants."""
from __future__ import annotations

from pathlib import Path

import pytest

from observatory.region_registry import RegionRegistry

# Matches the real glia/regions_registry.yaml schema: mapping keyed by region
# name, each value carries `layer` and `required_capabilities`.
REGISTRY_YAML = """\
schema_version: 1
regions:
  thalamus:
    layer: cognitive
    required_capabilities: [tool_use]
    default_capabilities: {tool_use: basic}
    singleton: true
  amygdala:
    layer: modulatory
    required_capabilities: []
    default_capabilities: {}
    singleton: true
"""


@pytest.fixture
def seeded(tmp_path: Path) -> RegionRegistry:
    glia_dir = tmp_path / "glia"
    glia_dir.mkdir()
    (glia_dir / "regions_registry.yaml").write_text(REGISTRY_YAML, encoding="utf-8")
    return RegionRegistry.seed_from(tmp_path)


def test_seed_loads_names_and_layer_as_role(seeded: RegionRegistry) -> None:
    names = sorted(seeded.names())
    assert names == ["amygdala", "thalamus"]
    assert seeded.get("thalamus").role == "cognitive"
    assert seeded.get("amygdala").role == "modulatory"


def test_heartbeat_updates_stats(seeded: RegionRegistry) -> None:
    seeded.apply_heartbeat("thalamus", {
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
        "phase": "wake",
        "queue_depth_messages": 0, "stm_bytes": 0,
        "llm_tokens_used_lifetime": 0, "handler_count": 0,
        "last_error_ts": None,
    })
    assert "hippocampus" in seeded.names()
    # role is empty when auto-registered (no entry in regions_registry.yaml)
    assert seeded.get("hippocampus").role == ""


def test_missing_registry_yaml_is_not_fatal(tmp_path: Path) -> None:
    reg = RegionRegistry.seed_from(tmp_path)
    assert reg.names() == []


def test_non_mapping_top_level_yaml_is_not_fatal(tmp_path: Path) -> None:
    """If someone serialises a list/scalar at the top level, don't crash."""
    glia_dir = tmp_path / "glia"
    glia_dir.mkdir()
    (glia_dir / "regions_registry.yaml").write_text("- foo\n- bar\n", encoding="utf-8")
    reg = RegionRegistry.seed_from(tmp_path)
    assert reg.names() == []


def test_non_mapping_regions_field_is_not_fatal(tmp_path: Path) -> None:
    glia_dir = tmp_path / "glia"
    glia_dir.mkdir()
    (glia_dir / "regions_registry.yaml").write_text(
        "regions:\n  - thalamus\n  - amygdala\n", encoding="utf-8"
    )
    reg = RegionRegistry.seed_from(tmp_path)
    assert reg.names() == []


def test_malformed_heartbeat_payload_preserves_prior_values(
    seeded: RegionRegistry,
) -> None:
    """A partial or badly-typed heartbeat must not drop all fields."""
    seeded.apply_heartbeat("thalamus", {
        "phase": "wake",
        "queue_depth_messages": 3,
        "stm_bytes": 1024,
        "llm_tokens_used_lifetime": 500,
        "handler_count": 4,
    })
    # Now a heartbeat with null/string-typed numerics arrives.
    seeded.apply_heartbeat("thalamus", {
        "phase": "processing",
        "queue_depth_messages": None,
        "stm_bytes": "n/a",
        "llm_tokens_used_lifetime": 600,
        "handler_count": None,
    })
    stats = seeded.get("thalamus").stats
    assert stats.phase == "processing"            # str field updated
    assert stats.queue_depth == 3                 # noqa: PLR2004 — fallback preserved
    assert stats.stm_bytes == 1024                # noqa: PLR2004 — fallback preserved
    assert stats.tokens_lifetime == 600           # noqa: PLR2004 — new value accepted
    assert stats.handler_count == 4               # noqa: PLR2004 — fallback preserved
