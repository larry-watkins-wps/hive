"""POST /sensory/text/in — validation, envelope construction, response shape."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import aiomqtt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from observatory.config import Settings
from observatory.sensory.errors import PublishFailedError
from observatory.sensory.routes import build_sensory_router, get_publisher, get_settings
from shared.message_envelope import Envelope


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def stub_publisher() -> MagicMock:
    pub = MagicMock()
    pub.publish = AsyncMock()
    return pub


@pytest.fixture
def app(settings: Settings, stub_publisher: MagicMock) -> FastAPI:
    a = FastAPI()
    a.include_router(build_sensory_router())
    a.dependency_overrides[get_publisher] = lambda: stub_publisher
    a.dependency_overrides[get_settings] = lambda: settings
    return a


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_happy_path_publishes_envelope_and_returns_id_timestamp(
    client: TestClient, stub_publisher: MagicMock, settings: Settings,
) -> None:
    """Spec §4.4: 202 + {id, timestamp} body; envelope per §3.2."""
    resp = client.post("/sensory/text/in", json={"text": "hi"})
    assert resp.status_code == 202  # noqa: PLR2004 — spec literal
    body = resp.json()
    assert "id" in body and len(body["id"]) >= 32  # noqa: PLR2004 — uuid hex string
    assert body["timestamp"].endswith("Z")

    stub_publisher.publish.assert_awaited_once()
    envelope: Envelope = stub_publisher.publish.call_args.args[0]
    assert envelope.topic == "hive/external/perception"
    assert envelope.source_region == "observatory.sensory"
    assert envelope.id == body["id"]
    assert envelope.timestamp == body["timestamp"]
    data = envelope.payload.data
    assert data["text"] == "hi"
    assert data["speaker"] == settings.chat_default_speaker
    assert data["channel"] == "observatory.chat"
    assert data["source_modality"] == "text"
    assert stub_publisher.publish.call_args.kwargs["qos"] == settings.chat_publish_qos


def test_speaker_override_passes_through(
    client: TestClient, stub_publisher: MagicMock,
) -> None:
    resp = client.post("/sensory/text/in", json={"text": "hi", "speaker": "Operator"})
    assert resp.status_code == 202  # noqa: PLR2004
    envelope: Envelope = stub_publisher.publish.call_args.args[0]
    assert envelope.payload.data["speaker"] == "Operator"


def test_text_trimmed_server_side(
    client: TestClient, stub_publisher: MagicMock,
) -> None:
    resp = client.post("/sensory/text/in", json={"text": "  hello  "})
    assert resp.status_code == 202  # noqa: PLR2004
    envelope: Envelope = stub_publisher.publish.call_args.args[0]
    assert envelope.payload.data["text"] == "hello"


def test_empty_after_trim_rejected_with_422(
    client: TestClient, stub_publisher: MagicMock,
) -> None:
    resp = client.post("/sensory/text/in", json={"text": "   "})
    assert resp.status_code == 422  # noqa: PLR2004
    stub_publisher.publish.assert_not_awaited()


def test_oversize_text_rejected_with_422(
    client: TestClient, stub_publisher: MagicMock, settings: Settings,
) -> None:
    too_long = "x" * (settings.chat_text_max_length + 1)
    resp = client.post("/sensory/text/in", json={"text": too_long})
    assert resp.status_code == 422  # noqa: PLR2004
    stub_publisher.publish.assert_not_awaited()


def test_publish_failed_returns_502(
    client: TestClient, stub_publisher: MagicMock,
) -> None:
    stub_publisher.publish.side_effect = PublishFailedError(
        aiomqtt.MqttError("broker down")
    )
    resp = client.post("/sensory/text/in", json={"text": "hi"})
    assert resp.status_code == 502  # noqa: PLR2004
    body = resp.json()
    assert body["error"] == "publish_failed"
    assert "broker down" in body["message"]


def test_response_has_no_store_cache_control(client: TestClient) -> None:
    resp = client.post("/sensory/text/in", json={"text": "hi"})
    assert resp.headers.get("Cache-Control") == "no-store"
