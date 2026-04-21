"""Pytest configuration for the smoke test directory.

Registers ``boot_all.py`` as a collectable test module so that
``pytest tests/smoke/`` discovers it without renaming it to ``test_*.py``.
The non-standard name is intentional: it signals that this directory is
a special smoke-test suite rather than a regular unit/integration suite.
"""
from __future__ import annotations

import pytest
from pathlib import Path


def pytest_collect_file(
    parent: pytest.Collector, file_path: Path
) -> pytest.Module | None:
    """Collect boot_all.py as a pytest module."""
    if file_path.name == "boot_all.py":
        return pytest.Module.from_parent(parent, path=file_path)
    return None
