"""REST router for v1: /api/health, /api/regions."""
from __future__ import annotations

from fastapi import APIRouter

from observatory import __version__
from observatory.region_registry import RegionRegistry


def build_router(region_registry: RegionRegistry) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/health")
    async def health() -> dict:
        return {"status": "ok", "version": __version__}

    @router.get("/regions")
    async def regions() -> dict:
        return {"regions": region_registry.to_json()}

    return router
