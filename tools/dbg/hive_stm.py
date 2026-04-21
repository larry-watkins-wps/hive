"""``hive stm <region>`` — pretty-print a region's short-term memory.

Task 7.3 per spec §H.3 (operator-side debug tool). Reads
``regions/<name>/memory/stm.json`` directly from the filesystem and
renders slots + recent events as human-readable text or raw JSON.

This tool intentionally bypasses the §D.6 MQTT query protocol (which is
for region-to-region access, not human observability). §H.3 authorizes
the filesystem path explicitly, including glia's read-only mount in
production; ``--root`` makes the path configurable for tests and
non-standard deployments.

Invocation: ``python -m tools.dbg.hive_stm <region> [flags]``.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import typer

app = typer.Typer(
    add_completion=False,
    help="Peek at a region's short-term memory (filesystem read, §H.3).",
    no_args_is_help=True,
)

_REGION_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
_DEFAULT_LIMIT = 20
_PREVIEW_MAX = 60
_EVENT_LINE_MAX = 80


# ---------------------------------------------------------------------------
# Root discovery
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _discover_root() -> Path:
    """Walk up from this file looking for a ``regions/`` dir or docker-compose anchor."""
    here = Path(__file__).resolve().parent
    for candidate in (here, *here.parents):
        if (candidate / "regions").is_dir() or (candidate / "docker-compose.yaml").is_file():
            return candidate
    typer.echo(
        f"error: could not locate Hive repo root (searched upward from {here}). "
        "Pass --root <path>.",
        err=True,
    )
    raise typer.Exit(code=2)


def _resolve_root(root: str | None) -> Path:
    if root is None:
        return _discover_root()
    path = Path(root).resolve()
    if not path.is_dir():
        typer.echo(f"error: --root {root} is not a directory.", err=True)
        raise typer.Exit(code=2)
    return path


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def _format_slot_value(value: object) -> str:
    if isinstance(value, str):
        return json.dumps(value)
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return repr(value)


def _event_preview(event: object) -> str:
    """One-line summary of a free-form event record."""
    if isinstance(event, dict):
        topic = event.get("topic")
        body = event.get("content")
        if body is None:
            body = event.get("data")
        if topic is not None and body is not None:
            body_str = body if isinstance(body, str) else json.dumps(body)
            snippet = body_str[:_PREVIEW_MAX]
            return f'{json.dumps(snippet)} (topic={topic})'
        if topic is not None:
            return f"(topic={topic})"
        if body is not None:
            body_str = body if isinstance(body, str) else json.dumps(body)
            return json.dumps(body_str[:_PREVIEW_MAX])
    # Fallback: full JSON preview.
    try:
        return json.dumps(event, default=str)[:_EVENT_LINE_MAX]
    except (TypeError, ValueError):
        return repr(event)[:_EVENT_LINE_MAX]


def _event_timestamp(event: object) -> str:
    if isinstance(event, dict):
        for key in ("ts", "timestamp", "received_at", "created_at", "at"):
            value = event.get(key)
            if isinstance(value, str):
                return value
    return "-"


def _render(data: dict, *, slots_only: bool, events_only: bool, limit: int) -> None:
    if not events_only:
        typer.echo(f"region:      {data.get('region', '?')}")
        typer.echo(f"updated_at:  {data.get('updated_at', '-')}")
        typer.echo(f"schema:      {data.get('schema_version', '-')}")

    slots = data.get("slots") or {}
    events = data.get("recent_events") or []

    if not events_only:
        typer.echo("")
        typer.echo(f"slots ({len(slots)}):")
        if not slots:
            typer.echo("  (none)")
        else:
            width = max((len(str(k)) for k in slots), default=0)
            for key, value in slots.items():
                typer.echo(f"  {str(key).ljust(width)}  {_format_slot_value(value)}")

    if not slots_only:
        total = len(events)
        shown = events[-limit:] if limit > 0 else events
        typer.echo("")
        header = f"recent events (last {len(shown)} of {total}):"
        typer.echo(header)
        if not shown:
            typer.echo("  (none)")
        else:
            for event in shown:
                typer.echo(f"  [{_event_timestamp(event)}] {_event_preview(event)}")


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


@app.command()
def main(  # noqa: PLR0913 — flag surface is the CLI contract
    region: str = typer.Argument(..., help="Region name (e.g., test_region)."),
    root: str | None = typer.Option(
        None,
        "--root",
        help="Override regions-parent directory (default: discover from repo layout).",
    ),
    raw: bool = typer.Option(False, "--raw", help="Print stm.json verbatim."),
    slots_only: bool = typer.Option(
        False, "--slots-only", help="Render only the slots section."
    ),
    events_only: bool = typer.Option(
        False, "--events-only", help="Render only the recent-events section."
    ),
    limit: int = typer.Option(
        _DEFAULT_LIMIT, "--limit", help="Max events to show (default 20)."
    ),
) -> None:
    """Pretty-print ``regions/<region>/memory/stm.json``."""
    if slots_only and events_only:
        typer.echo("error: --slots-only and --events-only are mutually exclusive.", err=True)
        raise typer.Exit(code=2)

    if not _REGION_NAME_RE.match(region):
        typer.echo(
            f"error: region name {region!r} is not valid (expected "
            "[a-zA-Z_][a-zA-Z0-9_]*; traversal characters rejected).",
            err=True,
        )
        raise typer.Exit(code=2)

    base = _resolve_root(root)
    stm_path = base / "regions" / region / "memory" / "stm.json"

    if not stm_path.is_file():
        typer.echo(
            f"error: stm.json not found at {stm_path}. "
            "Pass --root <path> if the regions tree lives elsewhere.",
            err=True,
        )
        raise typer.Exit(code=2)

    try:
        text = stm_path.read_text(encoding="utf-8")
    except OSError as exc:
        typer.echo(f"error: could not read {stm_path}: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        typer.echo(
            f"error: {stm_path} is malformed JSON ({exc.msg} at line "
            f"{exc.lineno}, col {exc.colno}).",
            err=True,
        )
        raise typer.Exit(code=1) from exc

    if not isinstance(data, dict):
        typer.echo(
            f"error: expected top-level JSON object in {stm_path}; got "
            f"{type(data).__name__}.",
            err=True,
        )
        raise typer.Exit(code=1)

    if raw:
        typer.echo(json.dumps(data, indent=2, default=str))
        return

    # Degrade gracefully if required keys are absent — warn but keep going.
    missing = [k for k in ("schema_version", "region", "slots") if k not in data]
    if missing:
        typer.echo(
            f"warning: {stm_path} is missing expected key(s): "
            f"{', '.join(missing)}. Rendering available fields.",
            err=True,
        )

    _render(data, slots_only=slots_only, events_only=events_only, limit=limit)


if __name__ == "__main__":  # pragma: no cover
    app()
