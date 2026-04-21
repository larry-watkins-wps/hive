"""CLI entry point: ``python -m observatory``.

Reads settings from env vars via ``Settings.from_env``, warns if bound to
a non-loopback host, then boots uvicorn with the FastAPI app constructed
by ``build_app``.
"""
from __future__ import annotations

import sys

import uvicorn

from observatory.config import Settings
from observatory.service import build_app


def main(argv: list[str] | None = None) -> int:  # noqa: ARG001
    settings = Settings.from_env()
    if settings.bind_host != "127.0.0.1":
        print(
            f"observatory: binding to non-loopback host {settings.bind_host!r} — "
            "make sure this is intentional.",
            file=sys.stderr,
        )
    app = build_app(settings)
    uvicorn.run(app, host=settings.bind_host, port=settings.bind_port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
