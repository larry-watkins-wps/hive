"""glia/registry.py — Regional anatomy registry (spec §F.3).

Loads ``glia/regions_registry.yaml`` and exposes the canonical list of
region types with their default capabilities.  The ``docker_spec()`` helper
returns a launcher-consumable dict (image/env/volumes) computed from
conventions so the YAML stays clean of deployment concerns.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ruamel.yaml import YAML

# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------

_YAML_SAFE = YAML(typ="safe")

_ALLOWED_LAYERS = frozenset(
    {"cognitive", "sensory", "motor", "modulatory", "homeostatic"}
)
_ALLOWED_TOP_LEVEL_KEYS = frozenset({"schema_version", "regions"})


class RegistryError(ValueError):
    """Raised when the registry YAML is structurally invalid."""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegistryEntry:
    """Immutable record for a single region type."""

    name: str
    layer: str  # cognitive | sensory | motor | modulatory | homeostatic
    required_capabilities: tuple[str, ...]
    default_capabilities: Mapping[str, Any]
    singleton: bool
    reserved: bool


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_DEFAULT_YAML = Path(__file__).parent / "regions_registry.yaml"


class RegionRegistry:
    """In-memory view of ``regions_registry.yaml``."""

    def __init__(
        self,
        schema_version: int,
        entries: dict[str, RegistryEntry],
    ) -> None:
        self.schema_version = schema_version
        self.entries: dict[str, RegistryEntry] = entries

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> RegionRegistry:
        """Load and validate the registry YAML.

        Parameters
        ----------
        path:
            Path to the YAML file.  Defaults to ``glia/regions_registry.yaml``
            (the sibling of this module).

        Raises
        ------
        RegistryError
            If the file is structurally invalid (unknown keys, missing required
            fields, bad layer values, etc.).
        FileNotFoundError
            If *path* does not exist.
        """
        if path is None:
            path = _DEFAULT_YAML

        try:
            with path.open("r", encoding="utf-8") as fh:
                raw: dict[str, Any] = _YAML_SAFE.load(fh)
        except FileNotFoundError:
            raise
        except Exception as exc:  # malformed YAML
            raise RegistryError(f"Failed to parse {path}: {exc}") from exc

        if raw is None:
            raise RegistryError(f"{path}: empty file")

        # ---- top-level key validation ----
        unknown = set(raw.keys()) - _ALLOWED_TOP_LEVEL_KEYS
        if unknown:
            raise RegistryError(
                f"{path}: unknown top-level key(s): {sorted(unknown)}"
            )

        if "schema_version" not in raw:
            raise RegistryError(f"{path}: missing required key 'schema_version'")

        schema_version = raw["schema_version"]
        if schema_version != 1:
            raise RegistryError(
                f"{path}: unsupported schema_version {schema_version!r} (expected 1)"
            )

        raw_regions: dict[str, Any] = raw.get("regions") or {}
        entries: dict[str, RegistryEntry] = {}

        for region_name, block in raw_regions.items():
            # Note: ruamel.yaml typ="safe" silently last-wins on duplicate keys
            # at parse time, so this loop never sees duplicates.  The registry
            # is hand-maintained (or ACC-generated), so we accept that behaviour.

            if not isinstance(block, dict):
                raise RegistryError(
                    f"{path}: region {region_name!r} must be a mapping, got "
                    f"{type(block).__name__}"
                )

            entry = cls._parse_entry(path, region_name, block)
            entries[region_name] = entry

        return cls(schema_version=schema_version, entries=entries)

    @staticmethod
    def _parse_entry(path: Path, name: str, block: dict[str, Any]) -> RegistryEntry:
        """Parse and validate a single region block."""
        reserved: bool = bool(block.get("reserved", False))

        # layer is required for all entries (active and reserved)
        if "layer" not in block:
            raise RegistryError(
                f"{path}: region {name!r} missing required field 'layer'"
            )
        layer: str = block["layer"]
        if layer not in _ALLOWED_LAYERS:
            raise RegistryError(
                f"{path}: region {name!r} has invalid layer {layer!r}; "
                f"must be one of {sorted(_ALLOWED_LAYERS)}"
            )

        # singleton is required for all entries
        if "singleton" not in block:
            raise RegistryError(
                f"{path}: region {name!r} missing required field 'singleton'"
            )
        singleton: bool = bool(block["singleton"])

        if not reserved:
            # Active regions must have required_capabilities and default_capabilities
            if "required_capabilities" not in block:
                raise RegistryError(
                    f"{path}: active region {name!r} missing 'required_capabilities'"
                )
            if "default_capabilities" not in block:
                raise RegistryError(
                    f"{path}: active region {name!r} missing 'default_capabilities'"
                )

        required_capabilities: tuple[str, ...] = tuple(
            block.get("required_capabilities") or []
        )
        default_capabilities: Mapping[str, Any] = MappingProxyType(
            dict(block.get("default_capabilities") or {})
        )

        return RegistryEntry(
            name=name,
            layer=layer,
            required_capabilities=required_capabilities,
            default_capabilities=default_capabilities,
            singleton=singleton,
            reserved=reserved,
        )

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def active(self) -> list[RegistryEntry]:
        """Return the 14 non-reserved entries in stable insertion order."""
        return [e for e in self.entries.values() if not e.reserved]

    def get(self, name: str) -> RegistryEntry:
        """Look up a region by name.

        Raises
        ------
        KeyError
            If *name* is not in the registry.
        """
        try:
            return self.entries[name]
        except KeyError:
            raise KeyError(name) from None

    def __contains__(self, name: str) -> bool:
        return name in self.entries

    # ------------------------------------------------------------------
    # Launcher helper
    # ------------------------------------------------------------------

    def docker_spec(self, name: str) -> dict[str, Any]:
        """Return a launcher-consumable Docker spec for an active region.

        The returned dict is suitable for passing to ``docker.containers.run``
        (or the glia supervisor).  All fields are computed from conventions
        rather than stored in the YAML.

        Parameters
        ----------
        name:
            Region name (must be in the registry and not reserved).

        Raises
        ------
        KeyError
            If *name* is not in the registry.
        ValueError
            If the region is reserved (no container runs at v0).
        """
        entry = self.get(name)  # raises KeyError if absent
        if entry.reserved:
            raise ValueError(
                f"Region {name!r} is reserved — no container runs at v0"
            )

        return {
            "image": "hive-region:v0",
            "name": f"hive-{name}",
            "env": {"HIVE_REGION": name},
            "volumes": {
                f"./regions/{name}": {
                    "bind": "/hive/region",
                    "mode": "rw",
                },
                "./region_template": {
                    "bind": "/hive/region_template",
                    "mode": "ro",
                },
                "./shared": {
                    "bind": "/hive/shared",
                    "mode": "ro",
                },
            },
            "network": "hive_net",
            "detach": True,
        }
