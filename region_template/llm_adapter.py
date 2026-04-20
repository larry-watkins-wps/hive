"""LLM adapter — public interface used by regions via ``ctx.llm`` (spec §C).

Regions never import LiteLLM directly (Principle XI). The adapter is the
only approved entry point. Responsibilities per §C:

- Normalize typed Hive requests (``CompletionRequest``) into LiteLLM's
  OpenAI-compat dict format.
- Enforce capability declarations (vision, tool_use, stream) before calling
  the provider (§C.5.1).
- Pre-reserve tokens, gate on budget, and record actuals (§C.5.2, §C.11).
- Inject Anthropic ``cache_control`` markers per ``cache_strategy`` (§C.6).
- Call ``litellm.acompletion`` with exponential-jitter backoff for
  retryable errors (§C.7).
- Map LiteLLM exceptions to :class:`~region_template.errors.LlmError` via
  :mod:`region_template.llm_errors`.
- Extract usage + cost and record to the ``TokenLedger``.

LiteLLM is imported lazily inside methods to keep module-load cost low
(its own import chain pulls ~500 ms of provider deps).
"""
from __future__ import annotations

import asyncio
import random
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import structlog

from region_template.capability import requires_capability  # re-export for handlers
from region_template.config_loader import RegionConfig
from region_template.errors import CapabilityDenied, LlmError
from region_template.llm_cache import CacheStrategy, apply_cache_strategy
from region_template.llm_errors import (
    KIND_MALFORMED_TOOL_CALL,
    KIND_OVER_BUDGET,
    KIND_RATE_LIMIT_EXHAUSTED,
    KIND_STREAM_TRUNCATED,
    KIND_UNKNOWN,
    classify_litellm_exception,
)
from region_template.llm_providers import (
    extra_call_params,
    resolve_model_string,
    validate_provider_env,
)
from region_template.token_ledger import EffectiveUsage, TokenLedger, TokenUsage
from region_template.types import CapabilityProfile

__all__ = [
    "CompletionRequest",
    "CompletionResult",
    "ContentPart",
    "LlmAdapter",
    "Message",
    "Role",
    "StreamChunk",
    "Tool",
    "ToolCall",
    # Re-exports for convenience:
    "EffectiveUsage",
    "TokenUsage",
    "requires_capability",
]


log = structlog.get_logger(__name__)


# Rough bytes-per-token estimate used by `estimate_tokens` for reservations.
# Real tokenizers disagree (~3-5 chars/token depending on model/language);
# 4 is a widely-used rule of thumb and is fine for pre-reservation.
_CHARS_PER_TOKEN = 4

# Default jitter fraction applied to the exponential backoff (±25%).
_JITTER_FRACTION = 0.25

# Threshold at which a tool list requires ``tool_use: advanced``
# (spec §C.5.1: "advanced" if len(req.tools) > 3 else "basic").
_TOOL_USE_ADVANCED_THRESHOLD = 3


# ---------------------------------------------------------------------------
# Public dataclasses (spec §C.3)
# ---------------------------------------------------------------------------


Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class ContentPart:
    """A single piece of a multimodal message.

    ``type``:
      - ``"text"``   → ``data`` is a ``str``.
      - ``"image"``  → ``data`` is a dict ``{"url": "..."}`` or bytes.
      - ``"audio"``  → ``data`` is a bytes reference or URL dict.
    """

    type: Literal["text", "image", "audio"]
    data: Any


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]  # JSON Schema


@dataclass(frozen=True)
class Message:
    """An LLM chat-completion message.

    ``content`` is either a bare string (plain text) or a list of
    :class:`ContentPart` for multimodal input.
    """

    role: Role
    content: str | list[ContentPart]
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None


@dataclass(frozen=True)
class CompletionRequest:
    messages: Sequence[Message]
    tools: Sequence[Tool] = ()
    max_tokens: int = 2048
    temperature: float = 0.7
    top_p: float = 1.0
    stop: Sequence[str] = ()
    stream: bool = False
    cache_strategy: CacheStrategy = "system"
    purpose: str = "general"  # tagged in logs + ledger for analysis


@dataclass(frozen=True)
class CompletionResult:
    """The result of a non-streaming LLM call.

    ``cached_prefix_tokens`` mirrors ``usage.cache_read_tokens`` — it's the
    same number exposed as a convenience for telemetry per §C.6.1.
    """

    text: str
    tool_calls: tuple[ToolCall, ...]
    finish_reason: Literal["stop", "length", "tool_calls", "content_filter", "error"]
    usage: TokenUsage
    model: str
    cached_prefix_tokens: int
    elapsed_ms: int
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StreamChunk:
    """A single streaming delta. Terminal chunk has ``finish_reason``."""

    delta_text: str = ""
    tool_delta: ToolCall | None = None
    finish_reason: str | None = None


# ---------------------------------------------------------------------------
# LlmAdapter
# ---------------------------------------------------------------------------


class LlmAdapter:
    """Public interface used by handlers via ``ctx.llm``.

    One instance per region. Constructed at bootstrap after config loading
    and capability-profile validation. Raises :class:`ConfigError` from
    ``__init__`` if the configured provider is unknown or its required env
    var is missing (§C.10).
    """

    def __init__(
        self,
        config: RegionConfig,
        capability_profile: CapabilityProfile,
        ledger: TokenLedger,
    ) -> None:
        validate_provider_env(config.llm.provider)
        self._cfg = config
        self._caps = capability_profile
        self._ledger = ledger
        # Pre-compute the LiteLLM model string so per-call overhead is nil.
        self._model_string = resolve_model_string(config.llm)
        self._log = log.bind(region=config.name, llm_model=config.llm.model)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def complete(self, req: CompletionRequest) -> CompletionResult:
        """Run a non-streaming LLM call.

        Raises:
          :class:`CapabilityDenied`: request needs a capability this region
            didn't declare (vision, ``tool_use:{basic,advanced}``, stream).
          :class:`LlmError`: provider returned a non-retryable error, all
            retryable attempts exhausted, or the ledger is over budget.
        """
        self._verify_capabilities(req)

        # Spec §C.5: reserve BEFORE checking budget so a self-tipping request
        # (one whose own estimate would push a clean ledger over the cap) is
        # rejected, not just requests already-over from prior reservations.
        estimate = self.estimate_tokens(req.messages)
        handle = self._ledger.reserve(estimate)
        self._raise_if_over_budget(handle)

        # Warning-threshold logging — best-effort, non-failing. Runs after
        # reserve so the warning reflects the post-reservation state.
        bucket = self._ledger.over_warning_threshold()
        if bucket is not None:
            self._log.warning("llm_over_budget.warning", bucket=bucket)

        try:
            messages_dicts = _to_litellm_messages(req.messages)
            messages_dicts = apply_cache_strategy(messages_dicts, req.cache_strategy)

            started = time.monotonic()
            raw = await self._call_with_retry(req, messages_dicts)
        except LlmError:
            self._ledger.release(handle)
            raise
        except BaseException:
            self._ledger.release(handle)
            raise

        try:
            usage = _extract_usage(raw)
            cost_usd = _compute_cost(raw)
            result = CompletionResult(
                text=_extract_text(raw),
                tool_calls=_extract_tool_calls(raw),
                finish_reason=_extract_finish_reason(raw),
                usage=usage,
                model=self._cfg.llm.model,
                cached_prefix_tokens=usage.cache_read_tokens,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                raw=_as_plain_dict(raw),
            )
        except LlmError:
            self._ledger.release(handle)
            raise

        self._ledger.record(handle, usage, cost_usd)
        return result

    async def stream(self, req: CompletionRequest) -> AsyncIterator[StreamChunk]:
        """Stream completion chunks.

        Requires ``capabilities.stream: true`` and ``req.stream=True``. The
        adapter accumulates output tokens chunk-by-chunk and records to the
        ledger on the terminal chunk (§C.13). Usage figures are best-effort:
        most providers only include final usage on the last chunk, so early
        chunks return zeros.

        Note: because this is an async generator, all pre-flight checks
        (capability, budget) run on first ``async for`` iteration, not on
        the initial ``adapter.stream(req)`` call.

        Failure during iteration raises
        ``LlmError("stream_truncated", retryable=False)``.
        """
        # Force stream=True to gate capability check correctly.
        stream_req = _replace_stream(req, True)
        self._verify_capabilities(stream_req)

        # Spec §C.5: reserve BEFORE checking budget (see complete() for rationale).
        estimate = self.estimate_tokens(req.messages)
        handle = self._ledger.reserve(estimate)
        self._raise_if_over_budget(handle)

        try:
            async for chunk in self._stream_impl(stream_req, handle):
                yield chunk
        except LlmError:
            self._ledger.release(handle)
            raise
        except BaseException:
            self._ledger.release(handle)
            raise

    def estimate_tokens(self, messages: Sequence[Message]) -> int:
        """Cheap token estimate over all text content.

        Good enough for pre-reservation: ~4 characters per token. Not
        suitable for billing. Ignores images/audio (their token cost is
        provider-specific and typically dominated by text in typical
        handler calls).
        """
        total_chars = 0
        for m in messages:
            if isinstance(m.content, str):
                total_chars += len(m.content)
            else:
                for part in m.content:
                    if part.type == "text" and isinstance(part.data, str):
                        total_chars += len(part.data)
        # Ensure at least 1 token is reserved even for tiny inputs.
        return max(1, total_chars // _CHARS_PER_TOKEN)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _verify_capabilities(self, req: CompletionRequest) -> None:
        """Raise :class:`CapabilityDenied` if the request exceeds declared caps."""
        # Vision: any image content part anywhere.
        for m in req.messages:
            if isinstance(m.content, list) and any(
                part.type == "image" for part in m.content
            ):
                if not self._caps.vision:
                    raise CapabilityDenied("vision")
                break

        # Tool use: "basic" for ≤3 tools, "advanced" for more.
        if req.tools:
            need = (
                "advanced"
                if len(req.tools) > _TOOL_USE_ADVANCED_THRESHOLD
                else "basic"
            )
            allowed = _at_least(need)
            if self._caps.tool_use not in allowed:
                raise CapabilityDenied(f"tool_use:{need}")

        # Streaming.
        if req.stream and not self._caps.stream:
            raise CapabilityDenied("stream")

    def _raise_if_over_budget(self, handle: str) -> None:
        """Raise ``over_budget`` and release ``handle`` if any bucket is over.

        Called after :meth:`TokenLedger.reserve` so the request's own estimate
        counts toward the budget check (§C.5 call-flow diagram).
        """
        bucket = self._ledger.over_budget()
        if bucket is not None:
            self._ledger.release(handle)
            self._log.error("llm_over_budget.hard", bucket=bucket)
            raise LlmError(KIND_OVER_BUDGET, retryable=False)

    def _backoff_seconds(self, attempt: int) -> float:
        """Exponential backoff with ±25% jitter, capped at ``max_backoff_s``.

        ``attempt`` is 1-based.
        """
        retry_cfg = self._cfg.llm.retry
        base = retry_cfg.initial_backoff_s * (2 ** (attempt - 1))
        jitter = base * _JITTER_FRACTION * (2 * random.random() - 1)  # noqa: S311
        return min(retry_cfg.max_backoff_s, max(0.0, base + jitter))

    async def _call_with_retry(
        self,
        req: CompletionRequest,
        messages_dicts: list[dict[str, Any]],
    ) -> Any:
        """Call ``litellm.acompletion`` with exponential retry on retryable errors."""
        import litellm  # noqa: PLC0415 — lazy, see module docstring

        retry_cfg = self._cfg.llm.retry
        call_kwargs = self._build_call_kwargs(req, messages_dicts)

        last_err: LlmError | None = None
        for attempt in range(1, retry_cfg.max_attempts + 1):
            try:
                return await litellm.acompletion(**call_kwargs)
            except Exception as exc:  # noqa: BLE001 — classify_* narrows it
                mapped = classify_litellm_exception(exc)
                mapped.__cause__ = exc
                if not mapped.retryable:
                    raise mapped from exc
                last_err = mapped
                if attempt >= retry_cfg.max_attempts:
                    # Convert retryable exhaustion into a non-retryable kind.
                    raise LlmError(KIND_RATE_LIMIT_EXHAUSTED, retryable=False) from exc
                delay = self._backoff_seconds(attempt)
                self._log.info(
                    "llm_retry",
                    attempt=attempt,
                    kind=mapped.kind,
                    delay_s=delay,
                )
                await asyncio.sleep(delay)
        # Defensive: shouldn't reach here because the loop either returns or raises.
        raise last_err or LlmError(KIND_UNKNOWN, retryable=False)

    def _build_call_kwargs(
        self,
        req: CompletionRequest,
        messages_dicts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Assemble kwargs for ``litellm.acompletion``.

        LiteLLM accepts OpenAI-compat kwargs + provider-specific fields via
        ``params``.
        """
        kwargs: dict[str, Any] = {
            "model": self._model_string,
            "messages": messages_dicts,
            "max_tokens": req.max_tokens,
            "temperature": req.temperature,
            "top_p": req.top_p,
        }
        if req.stop:
            kwargs["stop"] = list(req.stop)
        if req.stream:
            kwargs["stream"] = True
        if req.tools:
            kwargs["tools"] = [_tool_to_dict(t) for t in req.tools]
        # Merge region-level per-call params — these override the built-in
        # kwargs above so regions can tweak (e.g. Anthropic's top_k).
        kwargs.update(extra_call_params(self._cfg.llm))
        return kwargs

    async def _stream_impl(
        self,
        req: CompletionRequest,
        handle: str,
    ) -> AsyncIterator[StreamChunk]:
        """Internal streaming loop. Records ledger on terminal chunk.

        NOTE: ``complete()`` handles retries, but streaming retries are
        harder (partial output already sent). We make **one** attempt; if it
        fails mid-stream, we raise ``LlmError("stream_truncated")``.
        """
        import litellm  # noqa: PLC0415 — lazy, see module docstring

        messages_dicts = _to_litellm_messages(req.messages)
        messages_dicts = apply_cache_strategy(messages_dicts, req.cache_strategy)
        call_kwargs = self._build_call_kwargs(req, messages_dicts)
        call_kwargs["stream"] = True

        usage = TokenUsage(0, 0, 0, 0)
        try:
            response_iter = await litellm.acompletion(**call_kwargs)
            async for chunk in response_iter:
                delta_text, tool_delta, finish = _extract_stream_chunk(chunk)
                if chunk_usage := _maybe_extract_usage(chunk):
                    usage = chunk_usage
                yield StreamChunk(
                    delta_text=delta_text,
                    tool_delta=tool_delta,
                    finish_reason=finish,
                )
        except LlmError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise LlmError(KIND_STREAM_TRUNCATED, retryable=False) from exc

        # Record actuals on successful terminal chunk. Stream responses don't
        # carry a `completion_response` object compatible with
        # `litellm.completion_cost`, so compute from usage via
        # `litellm.cost_per_token`; fall back to 0 with WARN if unavailable.
        cost_usd = self._stream_cost_from_usage(usage)
        self._ledger.record(handle, usage, cost_usd)

    def _stream_cost_from_usage(self, usage: TokenUsage) -> float:
        """Compute stream cost from final usage via ``litellm.cost_per_token``.

        Returns 0.0 with a WARN log if the model isn't in LiteLLM's cost map
        (same failure mode as :func:`_compute_cost`). Billed input tokens are
        net of cache reads, matching the ledger's convention (§C.11).
        """
        try:
            import litellm  # noqa: PLC0415 — lazy

            billed_in = max(0, usage.input_tokens - usage.cache_read_tokens)
            prompt_cost, completion_cost = litellm.cost_per_token(
                model=self._model_string,
                prompt_tokens=billed_in,
                completion_tokens=usage.output_tokens,
            )
            return float(prompt_cost) + float(completion_cost)
        except Exception as exc:  # noqa: BLE001 — advisory
            self._log.warning("stream_cost_not_computed", error=str(exc))
            return 0.0


# ---------------------------------------------------------------------------
# Module-level helpers (pure)
# ---------------------------------------------------------------------------


def _at_least(level: Literal["basic", "advanced"]) -> set[str]:
    """Return the set of ``tool_use`` values that satisfy ``level``."""
    if level == "basic":
        return {"basic", "advanced"}
    return {"advanced"}


def _to_litellm_messages(messages: Sequence[Message]) -> list[dict[str, Any]]:
    """Convert :class:`Message` objects to LiteLLM dict shape.

    - Plain-text message → ``{"role": ..., "content": "..."}``.
    - Multi-part message → ``{"role": ..., "content": [{"type": ...}, ...]}``.
    """
    out: list[dict[str, Any]] = []
    for m in messages:
        d: dict[str, Any] = {"role": m.role}
        if isinstance(m.content, str):
            d["content"] = m.content
        else:
            d["content"] = [_content_part_to_dict(p) for p in m.content]
        if m.tool_calls:
            d["tool_calls"] = [_tool_call_to_dict(tc) for tc in m.tool_calls]
        if m.tool_call_id is not None:
            d["tool_call_id"] = m.tool_call_id
        out.append(d)
    return out


def _content_part_to_dict(part: ContentPart) -> dict[str, Any]:
    if part.type == "text":
        return {"type": "text", "text": part.data}
    if part.type == "image":
        # Accept either a URL dict or bytes. If it's already a dict pass through.
        if isinstance(part.data, dict):
            return {"type": "image_url", "image_url": dict(part.data)}
        return {"type": "image_url", "image_url": {"url": part.data}}
    # audio — LiteLLM's shape is provider-specific; we pass through.
    return {"type": "audio", "audio": part.data}


def _tool_to_dict(tool: Tool) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
        },
    }


def _tool_call_to_dict(tc: ToolCall) -> dict[str, Any]:
    return {
        "id": tc.id,
        "type": "function",
        "function": {"name": tc.name, "arguments": tc.arguments},
    }


def _replace_stream(req: CompletionRequest, stream: bool) -> CompletionRequest:
    """Return a copy of ``req`` with ``stream`` set. Frozen dataclass helper."""
    if req.stream == stream:
        return req
    return CompletionRequest(
        messages=req.messages,
        tools=req.tools,
        max_tokens=req.max_tokens,
        temperature=req.temperature,
        top_p=req.top_p,
        stop=req.stop,
        stream=stream,
        cache_strategy=req.cache_strategy,
        purpose=req.purpose,
    )


# ---------------------------------------------------------------------------
# Response-parsing helpers (defensive — LiteLLM's shape is ModelResponse,
# which is both attr-accessible and dict-accessible; we prefer dict access
# for portability).
# ---------------------------------------------------------------------------


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Access ``obj[key]`` or ``obj.key``, returning ``default`` on miss."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _extract_usage(raw: Any) -> TokenUsage:
    u = _get(raw, "usage", {}) or {}
    input_tokens = _get(u, "prompt_tokens", 0) or 0
    output_tokens = _get(u, "completion_tokens", 0) or 0
    # Anthropic-specific cache tokens via LiteLLM.
    cache_read = (
        _get(u, "cache_read_input_tokens")
        or _get(u, "prompt_cache_hit_tokens")
        or 0
    )
    cache_write = (
        _get(u, "cache_creation_input_tokens")
        or _get(u, "cache_write_tokens")
        or 0
    )
    return TokenUsage(
        input_tokens=int(input_tokens),
        output_tokens=int(output_tokens),
        cache_read_tokens=int(cache_read),
        cache_write_tokens=int(cache_write),
    )


def _maybe_extract_usage(chunk: Any) -> TokenUsage | None:
    """Return usage info if a stream chunk carries it, else ``None``."""
    usage = _get(chunk, "usage")
    if usage is None:
        return None
    return _extract_usage(chunk)


def _extract_text(raw: Any) -> str:
    choices = _get(raw, "choices") or []
    if not choices:
        return ""
    first = choices[0]
    message = _get(first, "message") or {}
    content = _get(message, "content") or ""
    # Some providers return content as list of parts on assistant messages;
    # flatten to text.
    if isinstance(content, list):
        parts = []
        for p in content:
            t = _get(p, "text")
            if t:
                parts.append(t)
        return "".join(parts)
    return str(content or "")


def _extract_tool_calls(raw: Any) -> tuple[ToolCall, ...]:
    choices = _get(raw, "choices") or []
    if not choices:
        return ()
    first = choices[0]
    message = _get(first, "message") or {}
    calls = _get(message, "tool_calls") or []
    out: list[ToolCall] = []
    for c in calls:
        fn = _get(c, "function") or {}
        args = _get(fn, "arguments")
        # LiteLLM returns the arguments as a JSON string; try to parse.
        if isinstance(args, str):
            try:
                import json  # noqa: PLC0415 — narrow scope, avoids top-level dep

                args = json.loads(args)
            except (ValueError, TypeError) as exc:
                raise LlmError(
                    KIND_MALFORMED_TOOL_CALL, retryable=False
                ) from exc
        out.append(
            ToolCall(
                id=_get(c, "id") or "",
                name=_get(fn, "name") or "",
                arguments=args if isinstance(args, dict) else {},
            )
        )
    return tuple(out)


def _extract_finish_reason(
    raw: Any,
) -> Literal["stop", "length", "tool_calls", "content_filter", "error"]:
    choices = _get(raw, "choices") or []
    if not choices:
        return "error"
    reason = _get(choices[0], "finish_reason") or "stop"
    if reason not in {"stop", "length", "tool_calls", "content_filter", "error"}:
        # Map OpenAI's "function_call" legacy → "tool_calls"; anything else → "stop".
        if reason == "function_call":
            return "tool_calls"
        return "stop"
    return reason  # type: ignore[return-value]


def _extract_stream_chunk(
    chunk: Any,
) -> tuple[str, ToolCall | None, str | None]:
    choices = _get(chunk, "choices") or []
    if not choices:
        return ("", None, None)
    first = choices[0]
    delta = _get(first, "delta") or {}
    text = _get(delta, "content") or ""
    tool_delta: ToolCall | None = None
    raw_tool_calls = _get(delta, "tool_calls") or []
    if raw_tool_calls:
        c = raw_tool_calls[0]
        fn = _get(c, "function") or {}
        tool_delta = ToolCall(
            id=_get(c, "id") or "",
            name=_get(fn, "name") or "",
            arguments={"_raw_arguments_delta": _get(fn, "arguments") or ""},
        )
    finish = _get(first, "finish_reason")
    return (str(text or ""), tool_delta, finish)


def _compute_cost(raw: Any) -> float:
    """Compute USD cost of a completion response. Returns 0.0 on failure.

    Uses ``litellm.completion_cost``. Unknown models or older LiteLLM builds
    without a cost table return 0.0 with a WARN log.
    """
    try:
        import litellm  # noqa: PLC0415 — lazy

        return float(litellm.completion_cost(completion_response=raw))
    except Exception as exc:  # noqa: BLE001 — advisory
        log.warning("llm_cost_unknown", error=str(exc))
        return 0.0


def _as_plain_dict(raw: Any) -> dict[str, Any]:
    """Best-effort conversion of a LiteLLM ModelResponse to a plain dict."""
    if isinstance(raw, dict):
        return dict(raw)
    # Most LiteLLM response types support .dict() or .model_dump().
    if hasattr(raw, "model_dump"):
        try:
            return raw.model_dump()  # type: ignore[no-any-return]
        except Exception:  # noqa: BLE001
            pass
    if hasattr(raw, "dict"):
        try:
            return raw.dict()  # type: ignore[no-any-return]
        except Exception:  # noqa: BLE001
            pass
    return {}
