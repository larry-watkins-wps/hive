"""Settings.from_env env-var parsing."""
from __future__ import annotations

import pytest

from observatory.config import ConfigError, Settings


def test_defaults_when_env_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "OBSERVATORY_BIND_HOST",
        "OBSERVATORY_BIND_PORT",
        "OBSERVATORY_MQTT_URL",
        "OBSERVATORY_RING_BUFFER_SIZE",
        "OBSERVATORY_MAX_WS_RATE",
        "OBSERVATORY_HIVE_ROOT",
    ):
        monkeypatch.delenv(key, raising=False)
    s = Settings.from_env()
    assert s.bind_host == "127.0.0.1"
    assert s.bind_port == 8765  # noqa: PLR2004
    assert s.mqtt_url == "mqtt://127.0.0.1:1883"


def test_env_overrides_are_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OBSERVATORY_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("OBSERVATORY_BIND_PORT", "9000")
    monkeypatch.setenv("OBSERVATORY_RING_BUFFER_SIZE", "42")
    s = Settings.from_env()
    assert s.bind_host == "0.0.0.0"
    assert s.bind_port == 9000  # noqa: PLR2004
    assert s.ring_buffer_size == 42  # noqa: PLR2004


def test_malformed_int_env_raises_config_error_with_var_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OBSERVATORY_BIND_PORT", "not-a-number")
    with pytest.raises(ConfigError, match="OBSERVATORY_BIND_PORT"):
        Settings.from_env()


def test_config_error_is_value_error_subclass() -> None:
    assert issubclass(ConfigError, ValueError)


def test_chat_defaults() -> None:
    """Spec §4.5 + §8 default table."""
    s = Settings()
    assert s.chat_default_speaker == "Larry"
    assert s.chat_publish_qos == 1
    assert s.chat_text_max_length == 4000  # noqa: PLR2004 — spec literal


def test_chat_default_speaker_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OBSERVATORY_CHAT_DEFAULT_SPEAKER", "Operator")
    s = Settings.from_env()
    assert s.chat_default_speaker == "Operator"


def test_chat_publish_qos_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OBSERVATORY_CHAT_PUBLISH_QOS", "0")
    s = Settings.from_env()
    assert s.chat_publish_qos == 0


def test_chat_text_max_length_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OBSERVATORY_CHAT_TEXT_MAX_LENGTH", "2000")
    s = Settings.from_env()
    assert s.chat_text_max_length == 2000  # noqa: PLR2004 — env literal


def test_chat_publish_qos_invalid_raises_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OBSERVATORY_CHAT_PUBLISH_QOS", "not-a-number")
    with pytest.raises(ConfigError):
        Settings.from_env()
