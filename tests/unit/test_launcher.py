"""Unit tests for glia.launcher — Task 5.3.

Covers:
  1.  launch_region issues docker.containers.run() with expected kwargs
      (image, name, network, env, volumes, detach, restart_policy,
      and resource limits).
  2.  Unknown region -> GliaError.
  3.  Reserved region -> GliaError (mentions "reserved").
  4.  Already-running region -> GliaError.
  5.  APIError / ImageNotFound are wrapped in GliaError.
  6.  MQTT_PASSWORD_<NAME> and ANTHROPIC_API_KEY are pulled from env
      when present, omitted when absent.
  7.  stop_region calls .stop(timeout=...) and .remove(); NotFound is a
      no-op; APIError -> GliaError.
  8.  restart_region stops then launches.
  9.  is_running: True for 'running', False for NotFound or non-running
      status.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from docker.errors import (  # type: ignore[import-untyped]
    APIError,
    ImageNotFound,
    NotFound,
)

from glia.launcher import DEFAULT_RESOURCE_LIMITS, GliaError, Launcher
from glia.registry import RegionRegistry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> RegionRegistry:
    """Load the real packaged registry (19 entries)."""
    return RegionRegistry.load()


@pytest.fixture
def mock_client() -> MagicMock:
    """A MagicMock standing in for docker.DockerClient."""
    client = MagicMock()
    # Default: container does not exist (is_running -> False).
    client.containers.get.side_effect = NotFound("no such container")
    return client


@pytest.fixture
def launcher(registry: RegionRegistry, mock_client: MagicMock) -> Launcher:
    return Launcher(registry=registry, client=mock_client)


# ---------------------------------------------------------------------------
# 1. launch_region — happy path kwargs
# ---------------------------------------------------------------------------


def test_launch_region_calls_docker_run_with_expected_kwargs(
    launcher: Launcher, mock_client: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Strip out any ambient secrets so env asserts are tight.
    monkeypatch.delenv("MQTT_PASSWORD_AMYGDALA", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    returned = MagicMock(name="Container")
    mock_client.containers.run.return_value = returned

    result = launcher.launch_region("amygdala")

    assert result is returned
    assert mock_client.containers.run.call_count == 1
    _, kwargs = mock_client.containers.run.call_args

    assert kwargs["image"] == "hive-region:v0"
    assert kwargs["name"] == "hive-amygdala"
    assert kwargs["network"] == "hive_net"
    assert kwargs["detach"] is True
    assert kwargs["restart_policy"] == {"Name": "unless-stopped"}

    env = kwargs["environment"]
    assert env["HIVE_REGION"] == "amygdala"
    assert env["MQTT_HOST"] == "broker"
    assert "MQTT_PASSWORD" not in env
    assert "ANTHROPIC_API_KEY" not in env

    # Volumes match the registry spec shape exactly.
    volumes = kwargs["volumes"]
    assert "./regions/amygdala" in volumes
    assert volumes["./regions/amygdala"] == {
        "bind": "/hive/region",
        "mode": "rw",
    }
    assert volumes["./region_template"] == {
        "bind": "/hive/region_template",
        "mode": "ro",
    }
    assert volumes["./shared"] == {
        "bind": "/hive/shared",
        "mode": "ro",
    }

    # Resource limits per spec §G.7.
    for key, val in DEFAULT_RESOURCE_LIMITS.items():
        assert kwargs[key] == val


# ---------------------------------------------------------------------------
# 2-4. Error paths on launch
# ---------------------------------------------------------------------------


def test_launch_region_unknown_raises_gliaerror(launcher: Launcher) -> None:
    with pytest.raises(GliaError, match="unknown region"):
        launcher.launch_region("not_a_region")


def test_launch_region_reserved_raises_gliaerror(launcher: Launcher) -> None:
    with pytest.raises(GliaError, match="reserved"):
        launcher.launch_region("raphe_nuclei")


def test_launch_region_already_running_raises(
    launcher: Launcher, mock_client: MagicMock
) -> None:
    # Simulate a running container of the same name.
    existing = MagicMock()
    existing.status = "running"
    mock_client.containers.get.side_effect = None
    mock_client.containers.get.return_value = existing

    with pytest.raises(GliaError, match="already running"):
        launcher.launch_region("amygdala")


# ---------------------------------------------------------------------------
# 5. Docker SDK errors -> GliaError
# ---------------------------------------------------------------------------


def test_launch_region_api_error_wrapped(
    launcher: Launcher, mock_client: MagicMock
) -> None:
    mock_client.containers.run.side_effect = APIError("boom")
    with pytest.raises(GliaError, match="docker API error"):
        launcher.launch_region("amygdala")


def test_launch_region_image_not_found_wrapped(
    launcher: Launcher, mock_client: MagicMock
) -> None:
    mock_client.containers.run.side_effect = ImageNotFound("no image")
    with pytest.raises(GliaError, match="image not found"):
        launcher.launch_region("amygdala")


# ---------------------------------------------------------------------------
# 6. Env injection
# ---------------------------------------------------------------------------


def test_launch_region_env_includes_mqtt_password_when_set(
    launcher: Launcher,
    mock_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MQTT_PASSWORD_AMYGDALA", "s3cret")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    launcher.launch_region("amygdala")
    _, kwargs = mock_client.containers.run.call_args
    assert kwargs["environment"]["MQTT_PASSWORD"] == "s3cret"


def test_launch_region_env_includes_anthropic_key_when_set(
    launcher: Launcher,
    mock_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MQTT_PASSWORD_AMYGDALA", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")

    launcher.launch_region("amygdala")
    _, kwargs = mock_client.containers.run.call_args
    assert kwargs["environment"]["ANTHROPIC_API_KEY"] == "sk-test-123"


def test_launch_region_env_omits_missing_secrets(
    launcher: Launcher,
    mock_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MQTT_PASSWORD_AMYGDALA", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    launcher.launch_region("amygdala")
    _, kwargs = mock_client.containers.run.call_args
    env = kwargs["environment"]
    # HIVE_REGION + MQTT_HOST only.
    assert set(env.keys()) == {"HIVE_REGION", "MQTT_HOST"}


# ---------------------------------------------------------------------------
# 7. stop_region
# ---------------------------------------------------------------------------


def test_stop_region_calls_stop_and_remove(
    launcher: Launcher, mock_client: MagicMock
) -> None:
    container = MagicMock()
    mock_client.containers.get.side_effect = None
    mock_client.containers.get.return_value = container

    launcher.stop_region("amygdala", timeout=7)

    mock_client.containers.get.assert_called_with("hive-amygdala")
    container.stop.assert_called_once_with(timeout=7)
    container.remove.assert_called_once_with()


def test_stop_region_not_found_is_noop(
    launcher: Launcher, mock_client: MagicMock
) -> None:
    # Default fixture side_effect is NotFound -> should not raise.
    launcher.stop_region("amygdala")
    mock_client.containers.get.assert_called_with("hive-amygdala")


def test_stop_region_api_error_wrapped(
    launcher: Launcher, mock_client: MagicMock
) -> None:
    container = MagicMock()
    container.stop.side_effect = APIError("cannot stop")
    mock_client.containers.get.side_effect = None
    mock_client.containers.get.return_value = container

    with pytest.raises(GliaError, match="docker API error stopping"):
        launcher.stop_region("amygdala")


def test_stop_region_remove_not_found_is_noop(
    launcher: Launcher, mock_client: MagicMock
) -> None:
    container = MagicMock()
    container.remove.side_effect = NotFound("already gone")
    mock_client.containers.get.side_effect = None
    mock_client.containers.get.return_value = container
    launcher.stop_region("amygdala")  # must not raise
    container.stop.assert_called_once()
    container.remove.assert_called_once()


# ---------------------------------------------------------------------------
# 8. restart_region
# ---------------------------------------------------------------------------


def test_restart_region_stop_then_launch(
    launcher: Launcher, mock_client: MagicMock
) -> None:
    # First .get() returns the running container (so stop has work to do),
    # subsequent .get() calls (is_running check in launch_region) raise
    # NotFound so the launch proceeds.
    existing = MagicMock()
    new_container = MagicMock(name="new")
    mock_client.containers.get.side_effect = [existing, NotFound("gone")]
    mock_client.containers.run.return_value = new_container

    result = launcher.restart_region("amygdala")

    existing.stop.assert_called_once()
    existing.remove.assert_called_once()
    mock_client.containers.run.assert_called_once()
    assert result is new_container


# ---------------------------------------------------------------------------
# 9. is_running
# ---------------------------------------------------------------------------


def test_is_running_true_when_status_running(
    launcher: Launcher, mock_client: MagicMock
) -> None:
    container = MagicMock()
    container.status = "running"
    mock_client.containers.get.side_effect = None
    mock_client.containers.get.return_value = container

    assert launcher.is_running("amygdala") is True
    container.reload.assert_called_once()


def test_is_running_false_when_not_found(
    launcher: Launcher, mock_client: MagicMock
) -> None:
    # Default fixture side_effect is NotFound.
    assert launcher.is_running("amygdala") is False


def test_is_running_false_when_status_exited(
    launcher: Launcher, mock_client: MagicMock
) -> None:
    container = MagicMock()
    container.status = "exited"
    mock_client.containers.get.side_effect = None
    mock_client.containers.get.return_value = container

    assert launcher.is_running("amygdala") is False


def test_launcher_uses_custom_broker_host(
    registry: RegionRegistry, mock_client: MagicMock
) -> None:
    launcher = Launcher(
        registry=registry, client=mock_client, broker_host="mqtt.internal"
    )
    launcher.launch_region("amygdala")
    _, kwargs = mock_client.containers.run.call_args
    assert kwargs["environment"]["MQTT_HOST"] == "mqtt.internal"


def test_launcher_uses_custom_env_loader(
    registry: RegionRegistry, mock_client: MagicMock
) -> None:
    def loader(region: str) -> dict[str, str]:
        return {"CUSTOM_VAR": f"val-{region}"}

    launcher = Launcher(registry=registry, client=mock_client, env_loader=loader)
    launcher.launch_region("amygdala")
    _, kwargs = mock_client.containers.run.call_args
    assert kwargs["environment"]["CUSTOM_VAR"] == "val-amygdala"
