"""``hive inject <topic> <payload_or_file>`` — craft and publish an envelope.

Task 7.4 per spec §H.3 (line 4101) and §K.2 (line 4462). The sole write
surface among the dbg tools; operator-authored traffic is labeled with
``source_region="hive_inject"`` (underscore, to match the schema regex
``^[a-z][a-z0-9_]{2,30}$``) in payload-shorthand mode so a downstream
observer can always tell a crafted message from an organic one.

Two modes:

* **Payload-shorthand** — the JSON contains ``data`` (and optionally
  ``content_type``). The tool synthesizes a full envelope via
  :meth:`shared.message_envelope.Envelope.new`. Matches the inline example
  in spec §K.2.
* **Full-envelope** — the JSON contains the complete envelope (with
  ``source_region`` *and* nested ``payload``). Validated verbatim via
  :meth:`Envelope.from_json`; the CLI ``<topic>`` argument MUST match
  ``envelope.topic`` (else exit 2). ``source_region`` is NOT mutated —
  the operator owns what they load.

Input sources:

* ``-`` → read from stdin,
* a string starting with ``{`` or ``[`` → treat as inline JSON,
* otherwise → a filesystem path.

Invocation::

    python -m tools.dbg.hive_inject <topic> <payload_or_file>
        [--host H] [--port N] [--qos 0|1|2] [--retain]
        [--correlation-id ID] [--reply-to TOPIC]

Exit codes:

* 0 — published,
* 1 — connection / publish failure (aiomqtt exception),
* 2 — usage error (malformed JSON, missing file, topic mismatch, schema).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Callable
from dataclasses import replace as dataclass_replace
from pathlib import Path
from typing import Any
from uuid import uuid4

import aiomqtt
import typer

from shared.message_envelope import Envelope, EnvelopeValidationError

# aiomqtt needs add_reader/add_writer, which the Proactor policy on Windows
# does not provide. Install the selector policy at import time.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 1883
DEFAULT_QOS = 1
DEFAULT_CONTENT_TYPE = "text/plain"
# Schema requires source_region to match ``^[a-z][a-z0-9_]{2,30}$`` (no
# hyphens) — so the operator label uses an underscore. The name still
# clearly identifies operator-injected traffic so observers can filter it out.
INJECT_SOURCE_REGION = "hive_inject"

# Indirection so tests can monkeypatch the factory used by the typer command
# without also re-exporting aiomqtt.Client.
_default_client_factory: Callable[..., Any] = aiomqtt.Client


app = typer.Typer(
    add_completion=False,
    help="Publish a crafted envelope to the Hive MQTT bus (operator tool).",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# Input resolution
# ---------------------------------------------------------------------------


def _load_raw(payload_or_file: str) -> str:
    """Resolve the CLI's second positional into a raw JSON string.

    Precedence:
      1. ``-`` → stdin,
      2. starts with ``{`` or ``[`` → inline JSON,
      3. otherwise → filesystem path (must exist).

    Raises ``typer.Exit(EXIT_USAGE)`` on a missing file (with the path in
    stderr, so the operator can see what was attempted).
    """
    if payload_or_file == "-":
        return sys.stdin.read()

    stripped = payload_or_file.lstrip()
    if stripped.startswith(("{", "[")):
        return payload_or_file

    path = Path(payload_or_file)
    if not path.is_file():
        typer.echo(f"error: file not found: {path}", err=True)
        raise typer.Exit(code=EXIT_USAGE)
    return path.read_text(encoding="utf-8")


def _looks_like_full_envelope(obj: Any) -> bool:
    """Heuristic: full envelopes have both ``source_region`` and a nested
    ``payload`` object. Payload-shorthand has neither.
    """
    return (
        isinstance(obj, dict)
        and "source_region" in obj
        and "payload" in obj
        and isinstance(obj["payload"], dict)
    )


# ---------------------------------------------------------------------------
# Envelope building
# ---------------------------------------------------------------------------


def _build_envelope(
    raw: str,
    *,
    topic: str,
    correlation_id: str | None,
    reply_to: str | None,
) -> Envelope:
    """Parse ``raw`` JSON into an :class:`Envelope`, applying either
    full-envelope or payload-shorthand semantics.

    Raises ``typer.Exit(EXIT_USAGE)`` on malformed JSON, schema violations,
    or a CLI-vs-envelope topic mismatch.
    """
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        typer.echo(f"error: malformed JSON: {exc}", err=True)
        raise typer.Exit(code=EXIT_USAGE) from exc

    if _looks_like_full_envelope(obj):
        # Full-envelope mode: validate verbatim, then only amend the
        # correlation_id / reply_to when the CLI flags were given.
        try:
            env = Envelope.from_json(raw.encode("utf-8"))
        except EnvelopeValidationError as exc:
            typer.echo(f"error: envelope validation failed: {exc}", err=True)
            raise typer.Exit(code=EXIT_USAGE) from exc

        if env.topic != topic:
            typer.echo(
                f"error: topic mismatch — CLI argument '{topic}' does not match "
                f"envelope.topic '{env.topic}'",
                err=True,
            )
            raise typer.Exit(code=EXIT_USAGE)

        # Flags win over the envelope when both are set (operator amending
        # a recorded envelope, per task spec).
        amended: dict[str, Any] = {}
        if correlation_id is not None:
            amended["correlation_id"] = correlation_id
        if reply_to is not None:
            amended["reply_to"] = reply_to
        if amended:
            env = dataclass_replace(env, **amended)
        return env

    # Payload-shorthand mode.
    if not isinstance(obj, dict) or "data" not in obj:
        typer.echo(
            "error: payload-shorthand JSON must be an object with a 'data' key "
            "(or a full envelope with 'source_region' and nested 'payload').",
            err=True,
        )
        raise typer.Exit(code=EXIT_USAGE)

    content_type = obj.get("content_type", DEFAULT_CONTENT_TYPE)
    try:
        env = Envelope.new(
            source_region=INJECT_SOURCE_REGION,
            topic=topic,
            content_type=content_type,
            data=obj["data"],
            correlation_id=correlation_id,
            reply_to=reply_to,
        )
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        typer.echo(f"error: could not build envelope: {exc}", err=True)
        raise typer.Exit(code=EXIT_USAGE) from exc

    # Validate the synthesized envelope against the schema so shorthand
    # users get the same bad-content-type feedback as full-envelope users.
    try:
        Envelope.from_json(env.to_json())
    except EnvelopeValidationError as exc:
        typer.echo(f"error: envelope validation failed: {exc}", err=True)
        raise typer.Exit(code=EXIT_USAGE) from exc
    return env


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------


async def _publish(
    env: Envelope,
    *,
    host: str,
    port: int,
    qos: int,
    retain: bool,
    client_factory: Callable[..., Any],
) -> int:
    """Connect, publish, disconnect. Returns the byte count of the payload."""
    username = os.environ.get("MQTT_USERNAME")
    password = os.environ.get("MQTT_PASSWORD")
    payload = env.to_json()
    async with client_factory(
        hostname=host,
        port=port,
        username=username,
        password=password,
        identifier=f"hive-inject-{uuid4()}",
    ) as client:
        await client.publish(env.topic, payload=payload, qos=qos, retain=retain)
    return len(payload)


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def run(
    topic: str,
    payload_or_file: str,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    qos: int = DEFAULT_QOS,
    retain: bool = False,
    correlation_id: str | None = None,
    reply_to: str | None = None,
    client_factory: Callable[..., Any] | None = None,
) -> int:
    """Synchronous entry point. Returns the process exit code."""
    factory = client_factory if client_factory is not None else _default_client_factory

    try:
        raw = _load_raw(payload_or_file)
    except typer.Exit as exc:
        return int(exc.exit_code)

    try:
        env = _build_envelope(
            raw,
            topic=topic,
            correlation_id=correlation_id,
            reply_to=reply_to,
        )
    except typer.Exit as exc:
        return int(exc.exit_code)

    try:
        nbytes = asyncio.run(
            _publish(
                env,
                host=host,
                port=port,
                qos=qos,
                retain=retain,
                client_factory=factory,
            )
        )
    except aiomqtt.MqttError as exc:
        typer.echo(f"error: publish failed: {exc}", err=True)
        return EXIT_FAIL

    typer.echo(
        f"published: {env.topic} (bytes={nbytes}, qos={qos}, retain={retain})"
    )
    return EXIT_OK


@app.command()
def inject(
    topic: str = typer.Argument(..., help="MQTT topic to publish onto."),
    payload_or_file: str = typer.Argument(
        ...,
        help="Inline JSON, path to a .json file, or '-' for stdin.",
    ),
    host: str = typer.Option(DEFAULT_HOST, "--host", help="MQTT broker hostname."),
    port: int = typer.Option(DEFAULT_PORT, "--port", help="MQTT broker port."),
    qos: int = typer.Option(DEFAULT_QOS, "--qos", help="QoS level (0, 1, or 2)."),
    retain: bool = typer.Option(False, "--retain", help="Set the retain flag."),
    correlation_id: str | None = typer.Option(
        None,
        "--correlation-id",
        help="Override the envelope's correlation_id.",
    ),
    reply_to: str | None = typer.Option(
        None,
        "--reply-to",
        help="Override the envelope's reply_to.",
    ),
) -> None:
    rc = run(
        topic,
        payload_or_file,
        host=host,
        port=port,
        qos=qos,
        retain=retain,
        correlation_id=correlation_id,
        reply_to=reply_to,
        client_factory=_default_client_factory,
    )
    raise typer.Exit(code=rc)


def main() -> None:  # pragma: no cover - trivial
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
