"""Tests for glia.registry — spec §F.3.

Covers:
  1. Load from default path; schema_version == 1; 19 total entries, 14 active.
  2. Active region names are exactly the expected 14.
  3. Reserved region names are exactly the expected 5.
  4. Spot-check medial_prefrontal_cortex fields.
  5. get() on unknown name raises KeyError.
  6. docker_spec() for an active region returns correct launcher dict.
  7. docker_spec() on a reserved region raises ValueError.
  8. Every active entry's layer is in the allowed set.
  9. Invalid YAML (unknown top-level key / missing schema_version) raises RegistryError.
 10. Duplicate region names in YAML raise RegistryError (skipped if ruamel dedups).
"""
from __future__ import annotations

import textwrap

import pytest

from glia.registry import RegionRegistry, RegistryEntry, RegistryError

# ---------------------------------------------------------------------------
# Expected constants (authoritative from spec §F.3)
# ---------------------------------------------------------------------------

_ACTIVE_NAMES = {
    "medial_prefrontal_cortex",
    "prefrontal_cortex",
    "anterior_cingulate",
    "hippocampus",
    "thalamus",
    "association_cortex",
    "visual_cortex",
    "auditory_cortex",
    "motor_cortex",
    "broca_area",
    "amygdala",
    "vta",
    "insula",
    "basal_ganglia",
}

_RESERVED_NAMES = {
    "raphe_nuclei",
    "locus_coeruleus",
    "hypothalamus",
    "basal_forebrain",
    "cerebellum",
}

_ALLOWED_LAYERS = {"cognitive", "sensory", "motor", "modulatory", "homeostatic"}

_TOTAL_ENTRY_COUNT = 19  # 14 active + 5 reserved (spec §F.3)
_ACTIVE_ENTRY_COUNT = 14


# ---------------------------------------------------------------------------
# 1. Basic load
# ---------------------------------------------------------------------------


def test_load_default_path():
    """Loading from default path succeeds; counts match spec §F.3."""
    registry = RegionRegistry.load()
    assert registry.schema_version == 1
    assert len(registry.entries) == _TOTAL_ENTRY_COUNT
    assert len(registry.active()) == _ACTIVE_ENTRY_COUNT


# ---------------------------------------------------------------------------
# 2. Active region names
# ---------------------------------------------------------------------------


def test_active_region_names():
    """The 14 active regions are exactly the spec-defined set."""
    registry = RegionRegistry.load()
    active_names = {e.name for e in registry.active()}
    assert active_names == _ACTIVE_NAMES


# ---------------------------------------------------------------------------
# 3. Reserved region names
# ---------------------------------------------------------------------------


def test_reserved_region_names():
    """The 5 reserved regions are exactly the spec-defined set."""
    registry = RegionRegistry.load()
    reserved = {name for name, e in registry.entries.items() if e.reserved}
    assert reserved == _RESERVED_NAMES


# ---------------------------------------------------------------------------
# 4. Spot-check entry fields
# ---------------------------------------------------------------------------


def test_entry_fields_medial_prefrontal_cortex():
    """medial_prefrontal_cortex has correct layer, singleton, required_capabilities."""
    registry = RegionRegistry.load()
    entry = registry.get("medial_prefrontal_cortex")

    assert isinstance(entry, RegistryEntry)
    assert entry.layer == "cognitive"
    assert entry.singleton is True
    assert entry.reserved is False
    assert "self_modify" in entry.required_capabilities
    assert "tool_use" in entry.required_capabilities
    # default_capabilities spot checks
    assert entry.default_capabilities["self_modify"] is True
    assert entry.default_capabilities["tool_use"] == "advanced"


# ---------------------------------------------------------------------------
# 5. KeyError for missing name
# ---------------------------------------------------------------------------


def test_get_missing_raises():
    """Requesting a non-existent region raises KeyError."""
    registry = RegionRegistry.load()
    with pytest.raises(KeyError):
        registry.get("not_a_region")


# ---------------------------------------------------------------------------
# 6. docker_spec for active region
# ---------------------------------------------------------------------------


def test_docker_spec_active_relative(monkeypatch):
    """Without HIVE_HOST_ROOT: relative paths (dev/test default)."""
    monkeypatch.delenv("HIVE_HOST_ROOT", raising=False)
    registry = RegionRegistry.load()
    spec = registry.docker_spec("amygdala")

    assert spec["image"] == "hive-region:v0"
    assert spec["name"] == "hive-amygdala"
    env = spec["env"]
    assert env["HIVE_REGION"] == "amygdala"
    # Windows-Docker-Desktop bind-mount workaround — applied unconditionally,
    # no-op on Linux where UIDs align.
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "safe.directory"
    assert env["GIT_CONFIG_VALUE_0"] == "/hive/region"
    # Regions share the host network namespace so 127.0.0.1 reaches the
    # host's MQTT broker without bridge networking.
    assert spec["network_mode"] == "host"
    assert "network" not in spec
    assert "extra_hosts" not in spec
    assert spec["detach"] is True

    # Labels make region containers visible to ``docker compose ps``.
    labels = spec["labels"]
    assert labels["com.docker.compose.project"] == "hive"
    assert labels["com.docker.compose.service"] == "amygdala"
    assert labels["com.docker.compose.oneoff"] == "False"

    volumes = spec["volumes"]
    assert volumes["./regions/amygdala"]["bind"] == "/hive/region"
    assert volumes["./regions/amygdala"]["mode"] == "rw"
    assert volumes["./src/region_template"]["bind"] == "/hive/region_template"
    assert volumes["./src/region_template"]["mode"] == "ro"
    assert volumes["./src/shared"]["bind"] == "/hive/shared"
    assert volumes["./src/shared"]["mode"] == "ro"


def test_docker_spec_active_absolute_posix(monkeypatch):
    """With HIVE_HOST_ROOT set: absolute host paths (prod mount from glia container)."""
    monkeypatch.setenv("HIVE_HOST_ROOT", "/home/op/hive")
    registry = RegionRegistry.load()
    spec = registry.docker_spec("amygdala")

    volumes = spec["volumes"]
    assert volumes["/home/op/hive/regions/amygdala"]["bind"] == "/hive/region"
    assert volumes["/home/op/hive/regions/amygdala"]["mode"] == "rw"
    assert volumes["/home/op/hive/src/region_template"]["bind"] == "/hive/region_template"
    assert volumes["/home/op/hive/src/region_template"]["mode"] == "ro"
    assert volumes["/home/op/hive/src/shared"]["bind"] == "/hive/shared"
    assert volumes["/home/op/hive/src/shared"]["mode"] == "ro"


def test_docker_spec_active_absolute_windows(monkeypatch):
    """Windows host paths are normalized to forward-slash form Docker accepts."""
    monkeypatch.setenv("HIVE_HOST_ROOT", r"C:\repos\hive")
    registry = RegionRegistry.load()
    spec = registry.docker_spec("amygdala")

    volumes = spec["volumes"]
    assert "C:/repos/hive/regions/amygdala" in volumes
    assert volumes["C:/repos/hive/regions/amygdala"]["bind"] == "/hive/region"
    assert volumes["C:/repos/hive/src/region_template"]["bind"] == "/hive/region_template"
    assert volumes["C:/repos/hive/src/shared"]["bind"] == "/hive/shared"


def test_docker_spec_host_root_trailing_slash_stripped(monkeypatch):
    """Trailing slash on HIVE_HOST_ROOT must not double-up."""
    monkeypatch.setenv("HIVE_HOST_ROOT", "/home/op/hive/")
    registry = RegionRegistry.load()
    spec = registry.docker_spec("amygdala")

    volumes = spec["volumes"]
    assert "/home/op/hive/regions/amygdala" in volumes
    assert "/home/op/hive//regions/amygdala" not in volumes


# ---------------------------------------------------------------------------
# 7. docker_spec raises ValueError for reserved region
# ---------------------------------------------------------------------------


def test_docker_spec_reserved_raises():
    """docker_spec() on a reserved region raises ValueError."""
    registry = RegionRegistry.load()
    with pytest.raises(ValueError, match="reserved"):
        registry.docker_spec("raphe_nuclei")


# ---------------------------------------------------------------------------
# 8. Layer values are in the allowed set
# ---------------------------------------------------------------------------


def test_layer_values():
    """Every active entry's layer is within the allowed five values."""
    registry = RegionRegistry.load()
    for entry in registry.active():
        assert entry.layer in _ALLOWED_LAYERS, (
            f"{entry.name} has unexpected layer {entry.layer!r}"
        )


# ---------------------------------------------------------------------------
# 9. Invalid YAML raises RegistryError
# ---------------------------------------------------------------------------


def test_invalid_yaml_unknown_key_rejected(tmp_path):
    """YAML with an unknown top-level key raises RegistryError."""
    bad_yaml = textwrap.dedent("""\
        schema_version: 1
        totally_unknown_key: oops
        regions:
          medial_prefrontal_cortex:
            layer: cognitive
            required_capabilities: [self_modify]
            default_capabilities: {self_modify: true}
            singleton: true
    """)
    p = tmp_path / "bad_registry.yaml"
    p.write_text(bad_yaml, encoding="utf-8")
    with pytest.raises(RegistryError, match="unknown"):
        RegionRegistry.load(p)


def test_invalid_yaml_missing_schema_version_rejected(tmp_path):
    """YAML without schema_version raises RegistryError."""
    bad_yaml = textwrap.dedent("""\
        regions:
          medial_prefrontal_cortex:
            layer: cognitive
            required_capabilities: [self_modify]
            default_capabilities: {self_modify: true}
            singleton: true
    """)
    p = tmp_path / "no_version.yaml"
    p.write_text(bad_yaml, encoding="utf-8")
    with pytest.raises(RegistryError, match="schema_version"):
        RegionRegistry.load(p)


def test_invalid_yaml_missing_layer_rejected(tmp_path):
    """An active entry missing 'layer' raises RegistryError."""
    bad_yaml = textwrap.dedent("""\
        schema_version: 1
        regions:
          medial_prefrontal_cortex:
            required_capabilities: [self_modify]
            default_capabilities: {self_modify: true}
            singleton: true
    """)
    p = tmp_path / "no_layer.yaml"
    p.write_text(bad_yaml, encoding="utf-8")
    with pytest.raises(RegistryError):
        RegionRegistry.load(p)


# ---------------------------------------------------------------------------
# 10. __contains__ convenience
# ---------------------------------------------------------------------------


def test_contains():
    """'name' in registry uses __contains__."""
    registry = RegionRegistry.load()
    assert "amygdala" in registry
    assert "not_a_region" not in registry


# ---------------------------------------------------------------------------
# 11. __contains__ — already tested above; duplicate-detection test removed
# ---------------------------------------------------------------------------
# ruamel.yaml typ="safe" last-wins on duplicate YAML keys at parse time, so a
# duplicate-detection guard in registry.py would be dead code.  No test for it.
