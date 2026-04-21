"""Shared fixtures for observatory unit tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture()
def regions_root(tmp_path: Path) -> Path:
    root = tmp_path / "regions"
    region = root / "testregion"
    (region / "memory").mkdir(parents=True)
    (region / "handlers").mkdir()
    (region / "prompt.md").write_text("# hello from testregion\n", encoding="utf-8")
    (region / "memory" / "stm.json").write_text(
        json.dumps({"note": "ok", "n": 3}), encoding="utf-8"
    )
    (region / "subscriptions.yaml").write_text(
        "topics:\n  - hive/modulator/+\n  - hive/self/identity\n",
        encoding="utf-8",
    )
    (region / "config.yaml").write_text(
        "name: testregion\n"
        "llm_model: fake-1.0\n"
        "api_key: topsecret\n"
        "nested:\n  auth_token: inner\n  aws_secret: [x, y]\n",
        encoding="utf-8",
    )
    (region / "handlers" / "on_wake.py").write_text(
        "def handle():\n    pass\n", encoding="utf-8"
    )
    return root
