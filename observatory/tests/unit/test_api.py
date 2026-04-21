from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from observatory.api import build_router
from observatory.region_registry import RegionRegistry


@pytest.fixture
def app() -> FastAPI:
    reg = RegionRegistry()
    reg.apply_heartbeat("thalamus", {
        "phase": "wake", "queue_depth_messages": 0, "stm_bytes": 0,
        "llm_tokens_used_lifetime": 0, "handler_count": 1, "last_error_ts": None,
    })
    app = FastAPI()
    app.include_router(build_router(region_registry=reg))
    return app


@pytest.mark.asyncio
async def test_health_returns_version(app: FastAPI) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/health")
    assert r.status_code == 200  # noqa: PLR2004
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body


@pytest.mark.asyncio
async def test_regions_returns_registry_json(app: FastAPI) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/regions")
    assert r.status_code == 200  # noqa: PLR2004
    body = r.json()
    assert "regions" in body
    assert "thalamus" in body["regions"]
    assert body["regions"]["thalamus"]["stats"]["phase"] == "wake"
