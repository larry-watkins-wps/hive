"""Cache-strategy marker injection (spec §C.6).

This module does **not** maintain a local cache. At v0, LLM-prompt caching
is entirely provider-side:

- **Anthropic** reads ``cache_control: {"type": "ephemeral"}`` markers on
  specific message content parts (5-minute TTL; 1024-token minimum).
- **OpenAI** prefix-caches automatically; no client-side action needed.
- **Ollama / vLLM** reuse KV cache automatically per-conversation.

Our job is therefore just to tag the request messages with Anthropic-style
markers according to ``cache_strategy``. LiteLLM's anthropic path passes the
marker through; the other provider paths either ignore the unknown field
(``drop_params: true`` in our LiteLLM config) or treat it as a no-op.

Shape
-----

Input is a list of **LiteLLM-shape** message dicts::

    [{"role": "system", "content": "..."}, ...]

or, for multi-part content::

    [{"role": "user", "content": [
        {"type": "text", "text": "..."},
        {"type": "image_url", "image_url": {"url": "..."}},
    ]}, ...]

Output is the same list with ``cache_control`` injected on the last content
part of the targeted messages per :data:`_STRATEGIES`.

Strategies
----------

- ``none`` → no markers.
- ``system`` → marker on last content part of the last system message.
- ``system_and_messages`` → marker on system + last two user messages.
"""
from __future__ import annotations

from typing import Any, Literal

__all__ = ["CacheStrategy", "apply_cache_strategy"]


CacheStrategy = Literal["none", "system", "system_and_messages"]

# The marker Anthropic looks for.
_EPHEMERAL_MARKER: dict[str, str] = {"type": "ephemeral"}


def apply_cache_strategy(
    messages: list[dict[str, Any]],
    strategy: CacheStrategy,
) -> list[dict[str, Any]]:
    """Return a deep-copied message list with cache_control markers applied.

    Pure function — the input is not mutated. Unknown strategy values raise
    ``ValueError`` (should be unreachable: upstream config validation closes
    the set).
    """
    if strategy == "none":
        return _deep_copy_messages(messages)

    if strategy not in {"system", "system_and_messages"}:
        raise ValueError(f"unknown cache strategy: {strategy!r}")

    out = _deep_copy_messages(messages)

    # Always tag the last system message in either strategy.
    last_system_idx = _last_index_for_role(out, "system")
    if last_system_idx is not None:
        _tag_last_content_part(out[last_system_idx])

    if strategy == "system_and_messages":
        # Tag the last two user messages (if fewer, tag what exists).
        user_indices = [i for i, m in enumerate(out) if m.get("role") == "user"]
        for idx in user_indices[-2:]:
            _tag_last_content_part(out[idx])

    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _deep_copy_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deep copy the outer list + each message dict + each content part.

    We deliberately avoid ``copy.deepcopy`` — messages may contain large bytes
    blobs (images) and we don't want to copy them. Instead we copy just the
    structure and share leaf values (strings, bytes, ints).
    """
    out: list[dict[str, Any]] = []
    for msg in messages:
        new_msg: dict[str, Any] = dict(msg)
        content = new_msg.get("content")
        if isinstance(content, list):
            new_msg["content"] = [dict(part) for part in content]
        out.append(new_msg)
    return out


def _last_index_for_role(
    messages: list[dict[str, Any]],
    role: str,
) -> int | None:
    """Return the index of the last message with ``role``, or ``None``."""
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == role:
            return i
    return None


def _tag_last_content_part(message: dict[str, Any]) -> None:
    """Attach an ``cache_control: {"type": "ephemeral"}`` marker in place.

    - If ``content`` is a string, convert to a single-part list so we can
      carry the marker. Anthropic's API requires the structured form when a
      marker is present.
    - If ``content`` is a list, tag the last part.
    - If ``content`` is missing or empty, this is a no-op (nothing to tag).
    """
    content = message.get("content")
    if content is None or content == "":
        return

    if isinstance(content, str):
        # Promote string content to a single text part so the marker fits.
        message["content"] = [
            {
                "type": "text",
                "text": content,
                "cache_control": dict(_EPHEMERAL_MARKER),
            }
        ]
        return

    if isinstance(content, list) and content:
        # Tag the last part (which is already a dict after _deep_copy_messages).
        last = content[-1]
        last["cache_control"] = dict(_EPHEMERAL_MARKER)
