"""Hive operator CLI.

Task 6.2 per spec §E.12 (narrowed to v0 by plan §6.2 Step 3):

* ``hive up [--dev | --no-docker --region NAME]``
* ``hive down [--fast]``
* ``hive status``
* ``hive logs SERVICE [--tail N] [--no-follow]``

Spec references: §G.1 (up sequence), §G.3 (down), §G.5 (dev mode),
§G.6 (``--no-docker`` escape hatch).

Invocation: ``python -m tools.hive_cli ...`` or ``python tools/hive_cli.py``.
A ``hive`` console script is deferred to install-time packaging.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import typer

app = typer.Typer(
    add_completion=False,
    help="Hive operator CLI (v0). Wraps docker compose for broker + glia.",
    no_args_is_help=True,
)

_VALID_LOG_SERVICES = ("broker", "glia")


# ---------------------------------------------------------------------------
# Repo root discovery
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def repo_root() -> Path:
    """Walk up from this file until we find ``docker-compose.yaml``.

    Cached because the layout never moves at runtime. Raises ``typer.Exit(2)``
    with a clear message if the file cannot be located (e.g., user renamed
    it or moved the script).
    """
    here = Path(__file__).resolve().parent
    for candidate in (here, *here.parents):
        if (candidate / "docker-compose.yaml").is_file():
            return candidate
    typer.echo(
        "error: could not locate docker-compose.yaml (searched upward from "
        f"{here}). Run hive_cli from within the Hive repository.",
        err=True,
    )
    raise typer.Exit(code=2)


# ---------------------------------------------------------------------------
# docker compose helpers
# ---------------------------------------------------------------------------


def _compose(*args: str, capture: bool = False) -> subprocess.CompletedProcess:
    """Run ``docker compose`` from the repo root.

    Uses ``check=False`` so the caller can surface the real exit code
    instead of a raw ``CalledProcessError`` stack trace.
    """
    argv = ["docker", "compose", *args]
    return subprocess.run(
        argv,
        cwd=repo_root(),
        capture_output=capture,
        text=True,
        check=False,
    )


def _exit_from(proc: subprocess.CompletedProcess) -> None:
    """Map a docker-compose failure to exit code 1 (spec contract)."""
    if proc.returncode != 0:
        typer.echo(
            f"error: `docker compose` exited {proc.returncode}",
            err=True,
        )
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# up
# ---------------------------------------------------------------------------


@app.command(help="Start Hive (broker + glia via docker compose).")
def up(
    dev: bool = typer.Option(
        False,
        "--dev",
        help="Dev mode: start broker only; skip glia and ACL enforcement (§G.5).",
    ),
    no_docker: bool = typer.Option(
        False,
        "--no-docker",
        help="Run one region directly against a local mosquitto binary (§G.6).",
    ),
    region: str | None = typer.Option(
        None,
        "--region",
        help="Region name to run under --no-docker.",
    ),
) -> None:
    if no_docker:
        if region is None:
            typer.echo(
                "error: --no-docker requires --region <name>",
                err=True,
            )
            raise typer.Exit(code=2)
        _up_no_docker(region)
        return

    if dev:
        if os.environ.get("HIVE_ENV") == "prod":
            typer.echo(
                "error: --dev is not allowed when HIVE_ENV=prod (spec §G.5).",
                err=True,
            )
            raise typer.Exit(code=2)
        typer.echo(
            "dev mode: starting broker only; glia + ACLs are NOT applied. "
            "Run regions separately with `python -m region_template ...`."
        )
        proc = _compose("up", "-d", "broker")
    else:
        proc = _compose("up", "-d")

    _exit_from(proc)
    typer.echo("hive up: done")


def _up_no_docker(region: str) -> None:
    """Launch mosquitto + one region directly, bypassing docker compose.

    Test-exercised branch: mosquitto binary absent → exit 2.
    Process-tree management is intentionally minimal; real multi-process
    orchestration lives in Phase 9 smoke tests.
    """
    mosquitto = shutil.which("mosquitto")
    if mosquitto is None:
        typer.echo(
            "error: `mosquitto` binary not found on PATH. Install Eclipse "
            "Mosquitto (https://mosquitto.org) or use `hive up` / `hive up --dev`.",
            err=True,
        )
        raise typer.Exit(code=2)

    config_path = repo_root() / "regions" / region / "config.yaml"
    if not config_path.is_file():
        typer.echo(
            f"error: no config at {config_path}; is `{region}` a valid region name?",
            err=True,
        )
        raise typer.Exit(code=2)

    # Prefer the repo-local broker config (ACLs, listeners, persistence) when
    # available. Fall back to a bare `-p 1883` with a warning so operators know
    # they're running without the Hive-shaped broker.
    mosquitto_conf = repo_root() / "bus" / "mosquitto.conf"
    if mosquitto_conf.is_file():
        broker_argv = [mosquitto, "-c", str(mosquitto_conf)]
    else:
        typer.echo(
            f"warning: {mosquitto_conf} not found; starting mosquitto with "
            "default config on port 1883 (no Hive ACLs).",
            err=True,
        )
        broker_argv = [mosquitto, "-p", "1883"]

    typer.echo(f"no-docker: starting local mosquitto and region {region}...")
    broker = subprocess.Popen(  # noqa: S603 - argv is literal
        broker_argv,
        cwd=repo_root(),
    )
    region_proc = subprocess.Popen(  # noqa: S603
        [
            sys.executable,
            "-m",
            "region_template",
            "--config",
            str(config_path),
        ],
        cwd=repo_root(),
    )

    _already_terminated = False

    def _terminate(*_: object) -> None:
        nonlocal _already_terminated
        if _already_terminated:
            return
        _already_terminated = True
        for p in (region_proc, broker):
            if p.poll() is None:
                p.terminate()

    # SIGINT works on both POSIX and Windows (Ctrl-C). SIGTERM is only
    # meaningful on POSIX; on Windows the closest equivalent is SIGBREAK
    # (Ctrl-Break), which only exists on Windows.
    signal.signal(signal.SIGINT, _terminate)
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, _terminate)
    elif hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _terminate)

    try:
        rc = region_proc.wait()
        raise typer.Exit(code=rc)
    finally:
        _terminate()
        # Ensure the broker doesn't outlive the CLI invocation.
        if broker.poll() is None:
            try:
                broker.wait(timeout=5)
            except subprocess.TimeoutExpired:
                broker.kill()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    broker.wait(timeout=5)


# ---------------------------------------------------------------------------
# down
# ---------------------------------------------------------------------------


@app.command(help="Stop Hive (docker compose down).")
def down(
    fast: bool = typer.Option(
        False,
        "--fast",
        help=(
            "Skip 30s shutdown grace (SIGTERM then SIGKILL after 1s). "
            "Spec §G.3 dev iteration."
        ),
    ),
) -> None:
    args = ["down", "--timeout", "1"] if fast else ["down"]
    proc = _compose(*args)
    _exit_from(proc)
    typer.echo("hive down: done")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@app.command(help="Report broker + glia state via `docker compose ps`.")
def status() -> None:
    proc = _compose("ps", "--format", "json", capture=True)
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        typer.echo("Hive is not running.")
        return

    rows: list[dict[str, str]] = []
    for raw_line in proc.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            typer.echo(
                f"warning: skipping unparseable line: {line[:80]}",
                err=True,
            )
            continue
        # Newer `docker compose ps --format json` emits one JSON object per
        # line (NDJSON); older versions occasionally emit a single JSON array.
        # Handle both without crashing downstream `.get(...)` on a list.
        if isinstance(payload, list):
            rows.extend(payload)
        else:
            rows.append(payload)

    if not rows:
        typer.echo("Hive is not running.")
        return

    headers = ("NAME", "SERVICE", "STATE", "HEALTH")
    table = [headers]
    for row in rows:
        table.append(
            (
                str(row.get("Name", "?")),
                str(row.get("Service", "?")),
                str(row.get("State", "?")),
                str(row.get("Health", "") or "-"),
            )
        )
    widths = [max(len(r[i]) for r in table) for i in range(len(headers))]
    for i, row in enumerate(table):
        typer.echo("  ".join(col.ljust(widths[j]) for j, col in enumerate(row)))
        if i == 0:
            typer.echo("  ".join("-" * w for w in widths))


# ---------------------------------------------------------------------------
# logs
# ---------------------------------------------------------------------------


@app.command(help="Stream logs for a Hive service (broker or glia).")
def logs(
    service: str = typer.Argument(..., help="Service name: broker | glia."),
    tail: int = typer.Option(100, "--tail", help="Number of lines from the end."),
    follow: bool = typer.Option(
        True,
        "--follow/--no-follow",
        help="Follow log output (default: follow).",
    ),
) -> None:
    if service not in _VALID_LOG_SERVICES:
        valid = ", ".join(_VALID_LOG_SERVICES)
        typer.echo(
            f"error: unknown service '{service}'. Valid services: {valid}.",
            err=True,
        )
        raise typer.Exit(code=2)

    args = ["logs", "--tail", str(tail)]
    if follow:
        args.append("--follow")
    args.append(service)
    proc = _compose(*args)
    _exit_from(proc)


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


def main() -> None:  # pragma: no cover - trivial
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
