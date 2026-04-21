"""``hive trace <correlation_id>`` — stitch causal chains from the MQTT bus.

Task 7.1 per spec §H.4. Subscribes to ``hive/#`` on the broker, buffers
envelopes whose ``correlation_id`` matches the target, and prints them as
a timestamp-sorted timeline. Envelopes that lose correlation on the way
through a handler are invisible — the tool reports whatever it saw over
the timeout window and exits. Best-effort semantics.

Invocation::

    python -m tools.dbg.hive_trace <correlation_id> [--host H] [--port N]
                                   [--timeout SEC] [--live]

Default: tail live for up to ``--timeout`` seconds (default 30), then
print the sorted timeline. ``--live`` prints events as they arrive
(unsorted) and exits on Ctrl-C / timeout.

The ``client_factory`` parameter on :func:`run` is an injection seam for
tests: production code passes :class:`aiomqtt.Client`.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import uuid4

import aiomqtt
import typer

from shared.message_envelope import Envelope, EnvelopeValidationError

# aiomqtt requires add_reader/add_writer which the default Proactor policy on
# Windows does not provide. Install the selector policy at import time so both
# the CLI entry point and direct ``run()`` callers are covered.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXIT_OK = 0
EXIT_ERROR = 1

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 1883
DEFAULT_TIMEOUT_S = 30.0

TRACE_TOPIC_FILTER = "hive/#"
PAYLOAD_PREVIEW_MAX = 60


app = typer.Typer(
    add_completion=False,
    help="Stitch envelopes sharing a correlation_id into a causal timeline.",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _preview(env: Envelope) -> str:
    """Render a short, safe payload preview.

    For ``text/plain`` envelopes, show the first :data:`PAYLOAD_PREVIEW_MAX`
    characters of ``data`` (decoding bytes as UTF-8 with replacement). For
    everything else, show just the content_type — JSON/binary bodies are
    not expanded inline per spec §H.4 to keep the timeline readable (and to
    avoid leaking secrets from opaque payloads).
    """
    ct = env.payload.content_type
    if ct == "text/plain":
        data = env.payload.data
        if isinstance(data, bytes):
            text = data.decode("utf-8", errors="replace")
        elif isinstance(data, str):
            text = data
        else:
            # text/plain with non-str data is unusual; stringify defensively.
            text = json.dumps(data) if isinstance(data, (dict, list)) else str(data)
        if len(text) > PAYLOAD_PREVIEW_MAX:
            text = text[:PAYLOAD_PREVIEW_MAX]
        return f'"{text}"'
    return f"<{ct}>"


def _format(env: Envelope, correlation_id: str) -> str:
    return (
        f"corr={correlation_id}  "
        f"{env.timestamp}  "
        f"{env.source_region:<12} → {env.topic}  {_preview(env)}"
    )


# ---------------------------------------------------------------------------
# Core collect loop
# ---------------------------------------------------------------------------


async def _collect(
    correlation_id: str,
    *,
    host: str,
    port: int,
    timeout: float,
    live: bool,
    client_factory: Callable[..., Any],
) -> tuple[list[Envelope], int]:
    """Subscribe and buffer matching envelopes until ``timeout`` seconds elapse.

    If ``live`` is true, each matching envelope is echoed as it arrives; the
    returned list is still populated so the caller can decide whether to also
    print a sorted summary (current CLI does not — ``--live`` is stream-only).

    Returns a tuple of ``(matching_envelopes, chain_gap_count)`` where
    ``chain_gap_count`` is the number of envelopes observed without a
    ``correlation_id`` (a handler forgot to propagate, per spec §H.4).
    """
    username = os.environ.get("MQTT_USERNAME")
    password = os.environ.get("MQTT_PASSWORD")
    buffer: list[Envelope] = []
    chain_gaps = 0

    async def _inner() -> None:
        nonlocal chain_gaps
        async with client_factory(
            hostname=host,
            port=port,
            username=username,
            password=password,
            identifier=f"hive-trace-{uuid4()}",
        ) as client:
            await client.subscribe(TRACE_TOPIC_FILTER)
            async for msg in client.messages:
                try:
                    env = Envelope.from_json(msg.payload)
                except EnvelopeValidationError:
                    # Malformed envelope on the bus — skip, keep tailing.
                    continue
                if env.correlation_id is None:
                    chain_gaps += 1
                    continue
                if env.correlation_id != correlation_id:
                    continue
                buffer.append(env)
                if live:
                    typer.echo(_format(env, correlation_id))

    # TimeoutError is the expected terminator for a bounded live-tail.
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(_inner(), timeout=timeout)

    return buffer, chain_gaps


def _ts_key(env: Envelope) -> Any:
    """Sort key for timestamps. Normalizes ``Z`` suffix → ``+00:00`` and
    parses with :func:`datetime.fromisoformat`; on parse failure, falls
    back to the raw string so badly-formed timestamps still sort stably
    (lexicographically) relative to each other.
    """
    ts = env.timestamp
    normalized = ts[:-1] + "+00:00" if ts.endswith("Z") else ts
    try:
        return (0, datetime.fromisoformat(normalized))
    except ValueError:
        # Keep unparseable timestamps sorted after parseable ones.
        return (1, ts)


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def run(
    correlation_id: str,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    timeout: float = DEFAULT_TIMEOUT_S,
    live: bool = False,
    client_factory: Callable[..., Any] = aiomqtt.Client,
) -> int:
    """Run the trace synchronously and return an exit code.

    Exposed (not just the typer command) so tests can exercise the logic
    without going through the CLI runner and without mocking the module-
    level ``aiomqtt.Client`` reference. The ``client_factory`` kwarg is
    the injection seam.
    """
    try:
        collected, chain_gaps = asyncio.run(
            _collect(
                correlation_id,
                host=host,
                port=port,
                timeout=timeout,
                live=live,
                client_factory=client_factory,
            )
        )
    except KeyboardInterrupt:
        # Ctrl-C is a graceful exit per §H.4 (tool just reports what it has).
        collected = []
        chain_gaps = 0
    except aiomqtt.MqttError as exc:
        # §H.7 best-effort: no tracebacks on broker hiccups.
        typer.echo(f"error: broker unreachable: {exc}", err=True)
        return EXIT_ERROR

    if not live:
        # Print sorted-by-timestamp summary with robust ISO-8601 parsing
        # (handles mixed ``Z`` and ``+00:00`` suffixes).
        collected.sort(key=_ts_key)
        for env in collected:
            typer.echo(_format(env, correlation_id))

    typer.echo(
        f"done: {len(collected)} events matching corr={correlation_id}"
    )
    if chain_gaps > 0:
        typer.echo(
            f"warn: {chain_gaps} envelope(s) seen without correlation_id (chain-gap)",
            err=True,
        )
    return EXIT_OK


@app.command()
def trace(
    correlation_id: str = typer.Argument(
        ...,
        help="Target correlation_id to stitch together.",
    ),
    host: str = typer.Option(DEFAULT_HOST, "--host", help="MQTT broker hostname."),
    port: int = typer.Option(DEFAULT_PORT, "--port", help="MQTT broker port."),
    timeout: float = typer.Option(
        DEFAULT_TIMEOUT_S,
        "--timeout",
        help="Seconds to tail the bus before printing the timeline.",
    ),
    live: bool = typer.Option(
        False,
        "--live",
        help="Stream matching envelopes as they arrive (unsorted).",
    ),
) -> None:
    rc = run(
        correlation_id,
        host=host,
        port=port,
        timeout=timeout,
        live=live,
        client_factory=aiomqtt.Client,
    )
    raise typer.Exit(code=rc)


def main() -> None:  # pragma: no cover - trivial
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
