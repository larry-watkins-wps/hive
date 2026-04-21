"""CLI entry point: ``python -m observatory``.

Reads settings from env vars via ``Settings.from_env``, warns if bound to
a non-loopback host, then boots uvicorn with the FastAPI app constructed
by ``build_app``.
"""
from __future__ import annotations

import structlog
import uvicorn

from observatory.config import Settings
from observatory.service import build_app

log = structlog.get_logger(__name__)


def main(argv: list[str] | None = None) -> int:  # noqa: ARG001
    settings = Settings.from_env()
    if settings.bind_host != "127.0.0.1":
        log.warning(
            "observatory.non_loopback_bind",
            host=settings.bind_host,
            note="binding to non-loopback host — make sure this is intentional",
        )
    app = build_app(settings)
    uvicorn.run(app, host=settings.bind_host, port=settings.bind_port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
