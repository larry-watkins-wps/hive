"""REST router: v1 `/api/health`, `/api/regions`, plus v2 per-region reads.

v2 adds five read endpoints under `/api/regions/{name}/` (prompt, stm,
subscriptions, config, handlers). Each short-circuits to 404 if the region
is not in the registry (before any disk touch), maps `SandboxError.code`
-> HTTP status via `_ERROR_KIND`, and emits `Cache-Control: no-store`.

The registry and reader are looked up via `request.app.state.*` to keep
the router free of construction-time dependencies (tests can swap either
on a per-app basis).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from observatory import __version__
from observatory.region_reader import RegionReader, SandboxError
from observatory.region_registry import RegionRegistry

# SandboxError.code -> error-body "error" kind. Falls back to "sandbox"
# if the reader ever raises with an unexpected code (defensive).
_ERROR_KIND = {403: "sandbox", 404: "not_found", 413: "oversize", 502: "parse"}
_NO_STORE = {"Cache-Control": "no-store"}


def _error_detail(err: SandboxError) -> dict[str, str]:
    """Build the {"error", "message"} body required by spec §6.2."""
    return {"error": _ERROR_KIND.get(err.code, "sandbox"), "message": str(err)}


def _ensure_region(request: Request, name: str) -> None:
    """Raise 404 if the region is not registered.

    Runs before any reader call so unknown regions never touch disk.
    Registry is attached to ``app.state.registry`` by the service factory.
    """
    registry: RegionRegistry = request.app.state.registry
    if name not in registry.names():
        raise HTTPException(
            status_code=404,
            detail={
                "error": "not_found",
                "message": f"region {name!r} not registered",
            },
        )


def _reader(request: Request) -> RegionReader:
    """Fetch the sandboxed file reader from app state."""
    return request.app.state.reader


def build_router(region_registry: RegionRegistry) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/health")
    async def health() -> dict:
        return {"status": "ok", "version": __version__}

    @router.get("/regions")
    async def regions() -> dict:
        return {"regions": region_registry.to_json()}

    @router.get("/regions/{name}/prompt", response_class=PlainTextResponse)
    def get_prompt(name: str, request: Request) -> PlainTextResponse:
        _ensure_region(request, name)
        try:
            text = _reader(request).read_prompt(name)
        except SandboxError as e:
            raise HTTPException(status_code=e.code, detail=_error_detail(e)) from e
        return PlainTextResponse(
            text,
            media_type="text/plain; charset=utf-8",
            headers=_NO_STORE,
        )

    @router.get("/regions/{name}/appendix", response_class=PlainTextResponse)
    def get_appendix(name: str, request: Request) -> PlainTextResponse:
        _ensure_region(request, name)
        try:
            text = _reader(request).read_appendix(name)
        except SandboxError as e:
            raise HTTPException(status_code=e.code, detail=_error_detail(e)) from e
        return PlainTextResponse(
            text,
            media_type="text/plain; charset=utf-8",
            headers=_NO_STORE,
        )

    @router.get("/regions/{name}/stm")
    def get_stm(name: str, request: Request) -> JSONResponse:
        _ensure_region(request, name)
        try:
            data = _reader(request).read_stm(name)
        except SandboxError as e:
            raise HTTPException(status_code=e.code, detail=_error_detail(e)) from e
        return JSONResponse(data, headers=_NO_STORE)

    @router.get("/regions/{name}/subscriptions")
    def get_subscriptions(name: str, request: Request) -> JSONResponse:
        _ensure_region(request, name)
        try:
            data = _reader(request).read_subscriptions(name)
        except SandboxError as e:
            raise HTTPException(status_code=e.code, detail=_error_detail(e)) from e
        return JSONResponse(data, headers=_NO_STORE)

    @router.get("/regions/{name}/config")
    def get_config(name: str, request: Request) -> JSONResponse:
        _ensure_region(request, name)
        try:
            data = _reader(request).read_config(name)
        except SandboxError as e:
            raise HTTPException(status_code=e.code, detail=_error_detail(e)) from e
        return JSONResponse(data, headers=_NO_STORE)

    @router.get("/regions/{name}/handlers")
    def get_handlers(name: str, request: Request) -> JSONResponse:
        _ensure_region(request, name)
        try:
            entries = _reader(request).list_handlers(name)
        except SandboxError as e:
            raise HTTPException(status_code=e.code, detail=_error_detail(e)) from e
        body = [{"path": e.path, "size": e.size} for e in entries]
        return JSONResponse(body, headers=_NO_STORE)

    return router
