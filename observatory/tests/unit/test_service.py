"""Unit tests for the observatory service factory + MQTT URL parsing.

Task 7 scope: verify `build_app(settings)` assembles without a live broker
(smoke path) and `_parse_mqtt_url` handles the three shapes we care about
(default port, explicit port, `mqtts://` scheme).
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
from fastapi import FastAPI

from observatory.config import Settings
from observatory.service import _parse_mqtt_url, build_app


def _smoke_settings(tmp_path: Path) -> Settings:
    """Settings with regions_root pointed at a real (empty) tmp dir.

    Task 4 made ``RegionReader.__init__`` eager (fails fast if
    ``regions_root`` doesn't exist), so ``build_app(Settings())`` now
    depends on cwd containing a ``./regions/`` directory. The smoke
    tests supply a temp dir instead so they stay cwd-independent.
    """
    regions = tmp_path / "regions"
    regions.mkdir()
    return dataclasses.replace(Settings(), regions_root=regions)


class TestParseMqttUrl:
    def test_explicit_port(self) -> None:
        assert _parse_mqtt_url("mqtt://localhost:1883") == ("localhost", 1883)

    def test_default_port_when_missing(self) -> None:
        # No colon → fall back to 1883 per aiomqtt default.
        assert _parse_mqtt_url("mqtt://localhost") == ("localhost", 1883)

    def test_mqtts_scheme_parses_but_does_not_enable_tls(self) -> None:
        # v1 parses the host/port; TLS wiring is a v1.1 follow-up
        # (aiomqtt.Client(hostname=..., port=...) in service.build_app
        # does not turn on TLS for mqtts:// — see decisions.md).
        host, port = _parse_mqtt_url("mqtts://broker.example.com:8883")
        assert host == "broker.example.com"
        assert port == 8883  # noqa: PLR2004 — literal TLS port is the thing under test

    def test_host_with_non_standard_port(self) -> None:
        assert _parse_mqtt_url("mqtt://10.0.0.5:1884") == ("10.0.0.5", 1884)  # noqa: PLR2004


class TestBuildAppSmoke:
    def test_build_app_returns_fastapi_instance(self, tmp_path: Path) -> None:
        app = build_app(_smoke_settings(tmp_path))
        assert isinstance(app, FastAPI)

    def test_build_app_registers_api_and_ws_routes(self, tmp_path: Path) -> None:
        app = build_app(_smoke_settings(tmp_path))
        paths = {getattr(r, "path", None) for r in app.routes}
        # REST router is prefixed /api.
        assert "/api/health" in paths
        assert "/api/regions" in paths
        # WS router mounts /ws.
        assert "/ws" in paths

    def test_build_app_wraps_subscriber_dispatch(self, tmp_path: Path) -> None:
        # The factory swaps subscriber.dispatch for a wrapper that fans new
        # ring records to the ConnectionHub. We can't easily inspect the
        # wrapped function from outside, but we can confirm build_app did
        # not crash and that the app has a lifespan handler attached.
        app = build_app(_smoke_settings(tmp_path))
        assert app.router.lifespan_context is not None


@pytest.mark.parametrize(
    "url,expected",
    [
        ("mqtt://127.0.0.1:1883", ("127.0.0.1", 1883)),
        ("mqtt://broker", ("broker", 1883)),
        ("mqtts://tls-host:8883", ("tls-host", 8883)),
    ],
)
def test_parse_mqtt_url_parametrized(url: str, expected: tuple[str, int]) -> None:
    assert _parse_mqtt_url(url) == expected
