"""Tests for :mod:`region_template.llm_adapter` — spec §C.

Covers:

Capability enforcement (§C.5.1):
- Image in request without ``vision`` → :class:`CapabilityDenied`.
- 4+ tools with ``tool_use="basic"`` → :class:`CapabilityDenied` ("advanced").
- Stream request with ``stream=false`` → :class:`CapabilityDenied`.

Budget enforcement (§C.5.2):
- Ledger over budget before call → :class:`LlmError` with kind ``over_budget``.

Cache strategy injection (§C.6):
- ``none`` → no ``cache_control`` field anywhere.
- ``system`` → marker on last content part of last system message.
- ``system_and_messages`` → marker on system + last two user messages.

Retry (§C.7):
- Retry on ``RateLimitError`` and eventually succeed.
- Exhaust all attempts → :class:`LlmError` with ``retryable=False``.
- Non-retryable error returned immediately (no retry loop).

Provider env / bootstrap (§C.10):
- Unknown provider → :class:`ConfigError`.
- Missing env var → :class:`ConfigError`.

Token ledger integration:
- ``LiteLLM`` response with ``cache_read_input_tokens`` populates
  ``usage.cache_read_tokens`` and ``cached_prefix_tokens``.
- Ledger is debited with billed input (``input_tokens - cache_read_tokens``).

FakeLlmAdapter:
- Pops responses in order.
- Empty script raises ``RuntimeError`` on next call.
- ``assert_all_consumed`` raises if responses remain.
"""
from __future__ import annotations

import asyncio
from typing import Any

import litellm
import pytest

from region_template.capability import requires_capability  # noqa: F401 — re-export smoke
from region_template.config_loader import (
    LlmBudgets,
    LlmCaching,
    LlmConfig,
    LlmRetry,
    RegionConfig,
)
from region_template.errors import CapabilityDenied, ConfigError, LlmError
from region_template.llm_adapter import (
    CompletionRequest,
    CompletionResult,
    ContentPart,
    LlmAdapter,
    Message,
    StreamChunk,
    Tool,
    ToolCall,
)
from region_template.token_ledger import TokenLedger, TokenUsage
from region_template.types import CapabilityProfile
from tests.fakes.llm import FakeLlmAdapter

# ---------------------------------------------------------------------------
# Constants — keep ruff PLR2004 quiet.
# ---------------------------------------------------------------------------

_ANY_API_KEY = "test-key"
_INPUT_TOKENS = 100
_OUTPUT_TOKENS = 50
_CACHE_READ_TOKENS = 40
_EFFECTIVE_INPUT = _INPUT_TOKENS - _CACHE_READ_TOKENS
_EXPECTED_ATTEMPTS_ON_SUCCESS = 3
_TWO_CALLS = 2
_TWO_CHUNKS = 2


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_caps(**overrides: Any) -> CapabilityProfile:
    base = {
        "self_modify": False,
        "tool_use": "none",
        "vision": False,
        "audio": False,
        "stream": False,
        "can_spawn": False,
        "modalities": ["text"],
    }
    base.update(overrides)
    return CapabilityProfile(**base)


def _make_config(
    provider: str = "anthropic",
    model: str = "claude-haiku-4",
    retry_max_attempts: int = 3,
    caps_overrides: dict[str, Any] | None = None,
    budgets: LlmBudgets | None = None,
) -> RegionConfig:
    caps = _make_caps(**(caps_overrides or {}))
    return RegionConfig(
        schema_version=1,
        name="test_region",
        role="an honest test region used by unit tests exclusively",
        llm=LlmConfig(
            provider=provider,
            model=model,
            params={},
            budgets=budgets or LlmBudgets(),
            retry=LlmRetry(
                max_attempts=retry_max_attempts,
                initial_backoff_s=0.1,  # min allowed by pydantic
                max_backoff_s=1.0,  # min allowed by pydantic
            ),
            caching=LlmCaching(strategy="system", ttl_hint_s=60),
        ),
        capabilities=caps,
    )


@pytest.fixture
def anthropic_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set ANTHROPIC_API_KEY so adapter bootstrap succeeds."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", _ANY_API_KEY)


def _make_adapter(
    config: RegionConfig | None = None,
    caps: CapabilityProfile | None = None,
    budgets: LlmBudgets | None = None,
) -> LlmAdapter:
    cfg = config or _make_config()
    profile = caps or cfg.capabilities
    ledger = TokenLedger(budgets or cfg.llm.budgets)
    return LlmAdapter(cfg, profile, ledger)


def _make_success_response(
    text: str = "hello",
    input_tokens: int = _INPUT_TOKENS,
    output_tokens: int = _OUTPUT_TOKENS,
    cache_read: int = 0,
    cache_write: int = 0,
    finish_reason: str = "stop",
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a dict matching LiteLLM's acompletion response shape."""
    message: dict[str, Any] = {"content": text}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "choices": [{"message": message, "finish_reason": finish_reason}],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "cache_read_input_tokens": cache_read,
            "cache_creation_input_tokens": cache_write,
        },
        "model": "claude-haiku-4",
    }


def _patch_litellm(
    monkeypatch: pytest.MonkeyPatch,
    acompletion_impl: Any,
    cost_usd: float = 0.0,
) -> dict[str, Any]:
    """Replace litellm.acompletion + completion_cost.

    Returns a shared ``state`` dict tests can inspect (``calls``, etc.).
    """
    state: dict[str, Any] = {"calls": []}

    async def wrapped(**kwargs: Any) -> Any:
        state["calls"].append(kwargs)
        result = acompletion_impl(**kwargs)
        if asyncio.iscoroutine(result):
            return await result
        return result

    def fake_cost(*, completion_response: Any) -> float:  # noqa: ARG001
        return cost_usd

    monkeypatch.setattr(litellm, "acompletion", wrapped)
    monkeypatch.setattr(litellm, "completion_cost", fake_cost)
    return state


# ---------------------------------------------------------------------------
# Bootstrap / env validation (§C.10)
# ---------------------------------------------------------------------------


class TestBootstrap:
    def test_unknown_provider_raises_config_error(
        self, anthropic_env: None  # noqa: ARG002
    ) -> None:
        cfg = _make_config(provider="notarealprovider")
        with pytest.raises(ConfigError, match="unknown LLM provider"):
            _make_adapter(cfg)

    def test_missing_api_key_raises_config_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        cfg = _make_config(provider="anthropic")
        with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
            _make_adapter(cfg)

    def test_ollama_has_no_required_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OLLAMA_API_BASE", raising=False)
        cfg = _make_config(provider="ollama", model="llama3")
        # Must not raise — ollama env is optional (spec §C.10).
        _make_adapter(cfg)


# ---------------------------------------------------------------------------
# Capability enforcement (§C.5.1)
# ---------------------------------------------------------------------------


class TestCapabilityEnforcement:
    async def test_image_without_vision_raises(self, anthropic_env: None) -> None:  # noqa: ARG002
        adapter = _make_adapter()
        req = CompletionRequest(
            messages=[
                Message(
                    role="user",
                    content=[
                        ContentPart(type="text", data="describe"),
                        ContentPart(type="image", data={"url": "http://x"}),
                    ],
                )
            ]
        )
        with pytest.raises(CapabilityDenied, match="vision"):
            await adapter.complete(req)

    async def test_image_with_vision_is_allowed(
        self, anthropic_env: None, monkeypatch: pytest.MonkeyPatch  # noqa: ARG002
    ) -> None:
        cfg = _make_config(caps_overrides={"vision": True})
        adapter = _make_adapter(cfg)
        _patch_litellm(
            monkeypatch, lambda **kw: _make_success_response()  # noqa: ARG005
        )
        req = CompletionRequest(
            messages=[
                Message(
                    role="user",
                    content=[
                        ContentPart(type="text", data="x"),
                        ContentPart(type="image", data={"url": "http://x"}),
                    ],
                )
            ]
        )
        result = await adapter.complete(req)
        assert result.text == "hello"

    async def test_four_tools_with_basic_raises_advanced(
        self, anthropic_env: None  # noqa: ARG002
    ) -> None:
        cfg = _make_config(caps_overrides={"tool_use": "basic"})
        adapter = _make_adapter(cfg)
        tools = tuple(
            Tool(name=f"t{i}", description="d", input_schema={}) for i in range(4)
        )
        req = CompletionRequest(
            messages=[Message(role="user", content="hi")],
            tools=tools,
        )
        with pytest.raises(CapabilityDenied, match="tool_use:advanced"):
            await adapter.complete(req)

    async def test_three_tools_with_basic_allowed(
        self, anthropic_env: None, monkeypatch: pytest.MonkeyPatch  # noqa: ARG002
    ) -> None:
        cfg = _make_config(caps_overrides={"tool_use": "basic"})
        adapter = _make_adapter(cfg)
        _patch_litellm(
            monkeypatch, lambda **kw: _make_success_response()  # noqa: ARG005
        )
        tools = tuple(
            Tool(name=f"t{i}", description="d", input_schema={}) for i in range(3)
        )
        req = CompletionRequest(
            messages=[Message(role="user", content="hi")],
            tools=tools,
        )
        await adapter.complete(req)  # must not raise

    async def test_tool_use_none_rejects_any_tools(
        self, anthropic_env: None  # noqa: ARG002
    ) -> None:
        adapter = _make_adapter()  # default tool_use=none
        req = CompletionRequest(
            messages=[Message(role="user", content="hi")],
            tools=(Tool(name="t1", description="d", input_schema={}),),
        )
        with pytest.raises(CapabilityDenied, match="tool_use:basic"):
            await adapter.complete(req)

    async def test_stream_request_without_stream_cap_raises(
        self, anthropic_env: None  # noqa: ARG002
    ) -> None:
        adapter = _make_adapter()  # default stream=False
        req = CompletionRequest(
            messages=[Message(role="user", content="hi")],
            stream=True,
        )
        with pytest.raises(CapabilityDenied, match="stream"):
            await adapter.complete(req)


# ---------------------------------------------------------------------------
# Cache strategy (§C.6)
# ---------------------------------------------------------------------------


class TestCacheStrategy:
    def _messages_with_system(self) -> list[Message]:
        return [
            Message(role="system", content="You are a test system."),
            Message(role="user", content="What is it?"),
            Message(role="assistant", content="Mid-convo reply."),
            Message(role="user", content="Follow-up."),
        ]

    async def test_none_strategy_no_markers(
        self, anthropic_env: None, monkeypatch: pytest.MonkeyPatch  # noqa: ARG002
    ) -> None:
        adapter = _make_adapter()
        state = _patch_litellm(
            monkeypatch, lambda **kw: _make_success_response()  # noqa: ARG005
        )
        req = CompletionRequest(
            messages=self._messages_with_system(),
            cache_strategy="none",
        )
        await adapter.complete(req)

        sent = state["calls"][0]["messages"]
        for m in sent:
            content = m.get("content")
            if isinstance(content, list):
                for part in content:
                    assert "cache_control" not in part

    async def test_system_strategy_marks_last_system(
        self, anthropic_env: None, monkeypatch: pytest.MonkeyPatch  # noqa: ARG002
    ) -> None:
        adapter = _make_adapter()
        state = _patch_litellm(
            monkeypatch, lambda **kw: _make_success_response()  # noqa: ARG005
        )
        req = CompletionRequest(
            messages=self._messages_with_system(),
            cache_strategy="system",
        )
        await adapter.complete(req)

        sent = state["calls"][0]["messages"]
        system_msg = next(m for m in sent if m["role"] == "system")
        # System message's string content was promoted to a list with marker.
        assert isinstance(system_msg["content"], list)
        assert system_msg["content"][-1].get("cache_control") == {"type": "ephemeral"}

        # No user message has a marker under 'system' strategy.
        user_msgs = [m for m in sent if m["role"] == "user"]
        for um in user_msgs:
            content = um.get("content")
            if isinstance(content, list):
                for part in content:
                    assert "cache_control" not in part

    async def test_system_and_messages_marks_system_and_last_two_users(
        self, anthropic_env: None, monkeypatch: pytest.MonkeyPatch  # noqa: ARG002
    ) -> None:
        adapter = _make_adapter()
        state = _patch_litellm(
            monkeypatch, lambda **kw: _make_success_response()  # noqa: ARG005
        )
        messages = [
            Message(role="system", content="sys"),
            Message(role="user", content="u1"),
            Message(role="assistant", content="a1"),
            Message(role="user", content="u2"),
            Message(role="assistant", content="a2"),
            Message(role="user", content="u3"),
        ]
        req = CompletionRequest(messages=messages, cache_strategy="system_and_messages")
        await adapter.complete(req)

        sent = state["calls"][0]["messages"]

        def last_part_has_marker(msg: dict[str, Any]) -> bool:
            content = msg.get("content")
            if not isinstance(content, list) or not content:
                return False
            return content[-1].get("cache_control") == {"type": "ephemeral"}

        # System has marker
        assert last_part_has_marker(sent[0])
        # Users at indices 3 (u2) and 5 (u3) should be marked, u1 (idx 1) not.
        user_positions = [i for i, m in enumerate(sent) if m["role"] == "user"]
        assert not last_part_has_marker(sent[user_positions[0]])
        assert last_part_has_marker(sent[user_positions[1]])
        assert last_part_has_marker(sent[user_positions[2]])


# ---------------------------------------------------------------------------
# Retry policy (§C.7)
# ---------------------------------------------------------------------------


class TestRetry:
    async def test_retries_rate_limit_then_succeeds(
        self, anthropic_env: None, monkeypatch: pytest.MonkeyPatch  # noqa: ARG002
    ) -> None:
        attempt_box = {"n": 0}

        def impl(**_kw: Any) -> Any:
            attempt_box["n"] += 1
            if attempt_box["n"] < _EXPECTED_ATTEMPTS_ON_SUCCESS:
                raise litellm.RateLimitError(
                    message="429",
                    llm_provider="anthropic",
                    model="claude-haiku-4",
                )
            return _make_success_response()

        async def no_sleep(_s: float) -> None:
            return None

        _patch_litellm(monkeypatch, impl)
        monkeypatch.setattr(asyncio, "sleep", no_sleep)

        adapter = _make_adapter()
        req = CompletionRequest(messages=[Message(role="user", content="hi")])
        result = await adapter.complete(req)
        assert result.text == "hello"
        assert attempt_box["n"] == _EXPECTED_ATTEMPTS_ON_SUCCESS

    async def test_exhausted_retries_raises_llm_error(
        self, anthropic_env: None, monkeypatch: pytest.MonkeyPatch  # noqa: ARG002
    ) -> None:
        def impl(**_kw: Any) -> Any:
            raise litellm.RateLimitError(
                message="429",
                llm_provider="anthropic",
                model="claude-haiku-4",
            )

        async def no_sleep(_s: float) -> None:
            return None

        _patch_litellm(monkeypatch, impl)
        monkeypatch.setattr(asyncio, "sleep", no_sleep)

        adapter = _make_adapter()
        req = CompletionRequest(messages=[Message(role="user", content="hi")])
        with pytest.raises(LlmError) as excinfo:
            await adapter.complete(req)
        assert excinfo.value.retryable is False
        assert "rate_limit_exhausted" in str(excinfo.value.args[0])

    async def test_non_retryable_error_fails_fast(
        self, anthropic_env: None, monkeypatch: pytest.MonkeyPatch  # noqa: ARG002
    ) -> None:
        calls_box = {"n": 0}

        def impl(**_kw: Any) -> Any:
            calls_box["n"] += 1
            raise litellm.AuthenticationError(
                message="bad key",
                llm_provider="anthropic",
                model="claude-haiku-4",
            )

        _patch_litellm(monkeypatch, impl)
        adapter = _make_adapter()
        req = CompletionRequest(messages=[Message(role="user", content="hi")])
        with pytest.raises(LlmError) as excinfo:
            await adapter.complete(req)
        assert excinfo.value.retryable is False
        assert excinfo.value.args[0] == "auth"
        # Fail fast: only one attempt.
        assert calls_box["n"] == 1


# ---------------------------------------------------------------------------
# Budget enforcement (§C.5.2)
# ---------------------------------------------------------------------------


class TestBudget:
    async def test_over_budget_raises_before_provider_call(
        self, anthropic_env: None, monkeypatch: pytest.MonkeyPatch  # noqa: ARG002
    ) -> None:
        cfg = _make_config(budgets=LlmBudgets(per_hour_input_tokens=1000))
        calls_box = {"n": 0}

        def impl(**_kw: Any) -> Any:
            calls_box["n"] += 1
            return _make_success_response()

        _patch_litellm(monkeypatch, impl)
        ledger = TokenLedger(cfg.llm.budgets)
        # Seed the ledger past budget.
        ledger.reserve(2000)
        adapter = LlmAdapter(cfg, cfg.capabilities, ledger)
        req = CompletionRequest(messages=[Message(role="user", content="hi")])
        with pytest.raises(LlmError) as excinfo:
            await adapter.complete(req)
        assert excinfo.value.args[0] == "over_budget"
        assert excinfo.value.retryable is False
        # Provider was never called.
        assert calls_box["n"] == 0

    async def test_self_tipping_request_rejects(
        self, anthropic_env: None, monkeypatch: pytest.MonkeyPatch  # noqa: ARG002
    ) -> None:
        """A single large request on a clean ledger is rejected (§C.5 reserve-then-check).

        Prior implementation checked budget BEFORE reserve, missing the case
        where the request's own estimate alone would exceed the cap.
        """
        cfg = _make_config(budgets=LlmBudgets(per_hour_input_tokens=1000))
        calls_box = {"n": 0}

        def impl(**_kw: Any) -> Any:
            calls_box["n"] += 1
            return _make_success_response()

        _patch_litellm(monkeypatch, impl)
        ledger = TokenLedger(cfg.llm.budgets)
        adapter = LlmAdapter(cfg, cfg.capabilities, ledger)

        # Clean ledger — no prior reservations or records.
        assert ledger.effective_usage().input_hour == 0

        # Force the adapter's estimate above the cap. Using monkeypatch on
        # the instance's `estimate_tokens` is the least-fragile approach;
        # a very long string would also work.
        monkeypatch.setattr(
            adapter, "estimate_tokens", lambda _msgs: 5000  # noqa: ARG005
        )

        req = CompletionRequest(messages=[Message(role="user", content="hi")])
        with pytest.raises(LlmError) as excinfo:
            await adapter.complete(req)
        assert excinfo.value.args[0] == "over_budget"
        assert excinfo.value.retryable is False
        # Provider was never called.
        assert calls_box["n"] == 0
        # Reservation was released — ledger has no residual.
        assert ledger.effective_usage().input_hour == 0

    async def test_self_tipping_stream_request_rejects(
        self, anthropic_env: None, monkeypatch: pytest.MonkeyPatch  # noqa: ARG002
    ) -> None:
        """Same reserve-then-check guarantee for :meth:`LlmAdapter.stream`."""
        cfg = _make_config(
            budgets=LlmBudgets(per_hour_input_tokens=1000),
            caps_overrides={"stream": True},
        )
        ledger = TokenLedger(cfg.llm.budgets)
        adapter = LlmAdapter(cfg, cfg.capabilities, ledger)

        monkeypatch.setattr(
            adapter, "estimate_tokens", lambda _msgs: 5000  # noqa: ARG005
        )

        req = CompletionRequest(
            messages=[Message(role="user", content="hi")],
            stream=True,
        )
        with pytest.raises(LlmError) as excinfo:
            # `stream()` is an async generator — the raise occurs on first
            # iteration, not at call time.
            async for _chunk in adapter.stream(req):
                pass
        assert excinfo.value.args[0] == "over_budget"
        assert ledger.effective_usage().input_hour == 0


# ---------------------------------------------------------------------------
# Token ledger integration (§C.6.1, §C.11)
# ---------------------------------------------------------------------------


class TestLedgerIntegration:
    async def test_records_cache_read_as_discount(
        self, anthropic_env: None, monkeypatch: pytest.MonkeyPatch  # noqa: ARG002
    ) -> None:
        def impl(**_kw: Any) -> Any:
            return _make_success_response(
                input_tokens=_INPUT_TOKENS,
                output_tokens=_OUTPUT_TOKENS,
                cache_read=_CACHE_READ_TOKENS,
            )

        _patch_litellm(monkeypatch, impl)
        ledger = TokenLedger(LlmBudgets())
        adapter = LlmAdapter(_make_config(), _make_caps(), ledger)
        req = CompletionRequest(messages=[Message(role="user", content="hi")])
        result = await adapter.complete(req)

        assert result.usage.input_tokens == _INPUT_TOKENS
        assert result.usage.output_tokens == _OUTPUT_TOKENS
        assert result.usage.cache_read_tokens == _CACHE_READ_TOKENS
        # cached_prefix_tokens mirrors usage.cache_read_tokens per §C.6.1.
        assert result.cached_prefix_tokens == _CACHE_READ_TOKENS

        # Ledger billed input is input - cache_read.
        u = ledger.effective_usage()
        assert u.input_hour == _EFFECTIVE_INPUT

    async def test_failed_call_releases_reservation(
        self, anthropic_env: None, monkeypatch: pytest.MonkeyPatch  # noqa: ARG002
    ) -> None:
        def impl(**_kw: Any) -> Any:
            raise litellm.AuthenticationError(
                message="bad key",
                llm_provider="anthropic",
                model="claude-haiku-4",
            )

        _patch_litellm(monkeypatch, impl)
        ledger = TokenLedger(LlmBudgets())
        adapter = LlmAdapter(_make_config(), _make_caps(), ledger)
        req = CompletionRequest(
            messages=[Message(role="user", content="hi" * 100)]
        )
        with pytest.raises(LlmError):
            await adapter.complete(req)
        # No leaked reservation.
        assert ledger.effective_usage().input_hour == 0


# ---------------------------------------------------------------------------
# Streaming (§C.13)
# ---------------------------------------------------------------------------


class TestStreaming:
    """Stream path — cost computation + capability enforcement on iteration."""

    @staticmethod
    def _chunks_with_final_usage(
        input_tokens: int = _INPUT_TOKENS,
        output_tokens: int = _OUTPUT_TOKENS,
    ) -> list[dict[str, Any]]:
        """Build a few stream chunks; final chunk carries usage."""
        return [
            {
                "choices": [{"delta": {"content": "hel"}, "finish_reason": None}],
            },
            {
                "choices": [{"delta": {"content": "lo"}, "finish_reason": None}],
            },
            {
                "choices": [{"delta": {}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": input_tokens,
                    "completion_tokens": output_tokens,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                },
            },
        ]

    @staticmethod
    def _make_async_iter(chunks: list[dict[str, Any]]) -> Any:
        async def gen() -> Any:
            for c in chunks:
                yield c
        return gen()

    async def test_stream_records_nonzero_cost(
        self, anthropic_env: None, monkeypatch: pytest.MonkeyPatch  # noqa: ARG002
    ) -> None:
        """Stream path computes cost via ``litellm.cost_per_token`` (§C.11)."""
        cfg = _make_config(caps_overrides={"stream": True})
        ledger = TokenLedger(LlmBudgets())
        adapter = LlmAdapter(cfg, cfg.capabilities, ledger)

        chunks = self._chunks_with_final_usage()

        async def fake_acompletion(**_kw: Any) -> Any:
            return self._make_async_iter(chunks)

        # Make cost_per_token return a known non-zero tuple.
        expected_cost = 0.0007  # 0.0003 prompt + 0.0004 completion
        cost_calls: list[dict[str, Any]] = []

        def fake_cost_per_token(**kwargs: Any) -> tuple[float, float]:
            cost_calls.append(kwargs)
            return (0.0003, 0.0004)

        monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
        monkeypatch.setattr(litellm, "cost_per_token", fake_cost_per_token)

        # Wrap ledger.record to capture call args.
        record_args: list[tuple[str, TokenUsage, float]] = []
        real_record = ledger.record

        def spy_record(handle: str, usage: TokenUsage, cost_usd: float) -> None:
            record_args.append((handle, usage, cost_usd))
            real_record(handle, usage, cost_usd)

        monkeypatch.setattr(ledger, "record", spy_record)

        req = CompletionRequest(
            messages=[Message(role="user", content="hi")],
            stream=True,
        )
        collected = [c async for c in adapter.stream(req)]

        # Stream produced text chunks + terminal finish_reason.
        assert len(collected) == len(chunks)
        assert collected[-1].finish_reason == "stop"

        # Ledger was recorded exactly once, with the non-zero cost.
        assert len(record_args) == 1
        _handle, usage, cost = record_args[0]
        assert usage.input_tokens == _INPUT_TOKENS
        assert usage.output_tokens == _OUTPUT_TOKENS
        assert cost == pytest.approx(expected_cost)

        # And cost_per_token was called with the billed token counts.
        assert len(cost_calls) == 1
        assert cost_calls[0]["prompt_tokens"] == _INPUT_TOKENS  # no cache read
        assert cost_calls[0]["completion_tokens"] == _OUTPUT_TOKENS

    async def test_stream_cost_falls_back_to_zero_on_unknown_model(
        self, anthropic_env: None, monkeypatch: pytest.MonkeyPatch  # noqa: ARG002
    ) -> None:
        """If cost_per_token raises (unknown model), record 0 with WARN."""
        cfg = _make_config(caps_overrides={"stream": True})
        ledger = TokenLedger(LlmBudgets())
        adapter = LlmAdapter(cfg, cfg.capabilities, ledger)

        chunks = self._chunks_with_final_usage()

        async def fake_acompletion(**_kw: Any) -> Any:
            return self._make_async_iter(chunks)

        def blowup_cost_per_token(**_kw: Any) -> tuple[float, float]:
            raise ValueError("unknown model")

        monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
        monkeypatch.setattr(litellm, "cost_per_token", blowup_cost_per_token)

        record_args: list[tuple[str, TokenUsage, float]] = []
        real_record = ledger.record

        def spy_record(handle: str, usage: TokenUsage, cost_usd: float) -> None:
            record_args.append((handle, usage, cost_usd))
            real_record(handle, usage, cost_usd)

        monkeypatch.setattr(ledger, "record", spy_record)

        req = CompletionRequest(
            messages=[Message(role="user", content="hi")],
            stream=True,
        )
        async for _c in adapter.stream(req):
            pass

        # Recorded, but with cost 0.0 because lookup failed.
        assert len(record_args) == 1
        assert record_args[0][2] == 0.0

    async def test_stream_iteration_without_stream_cap_raises(
        self, anthropic_env: None  # noqa: ARG002
    ) -> None:
        """Iterating :meth:`stream` on a region without ``stream`` cap fails fast."""
        adapter = _make_adapter()  # default stream=False
        req = CompletionRequest(
            messages=[Message(role="user", content="hi")],
            stream=True,
        )
        with pytest.raises(CapabilityDenied, match="stream"):
            async for _c in adapter.stream(req):
                pass


# ---------------------------------------------------------------------------
# Routing to correct provider (§C.9)
# ---------------------------------------------------------------------------


class TestProviderRouting:
    async def test_anthropic_provider_prefixes_model(
        self, anthropic_env: None, monkeypatch: pytest.MonkeyPatch  # noqa: ARG002
    ) -> None:
        state = _patch_litellm(
            monkeypatch, lambda **kw: _make_success_response()  # noqa: ARG005
        )
        adapter = _make_adapter(_make_config(provider="anthropic", model="claude-haiku-4"))
        req = CompletionRequest(messages=[Message(role="user", content="hi")])
        await adapter.complete(req)
        assert state["calls"][0]["model"] == "anthropic/claude-haiku-4"

    async def test_openai_provider_prefixes_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", _ANY_API_KEY)
        state = _patch_litellm(
            monkeypatch, lambda **kw: _make_success_response()  # noqa: ARG005
        )
        adapter = _make_adapter(_make_config(provider="openai", model="gpt-4o"))
        req = CompletionRequest(messages=[Message(role="user", content="hi")])
        await adapter.complete(req)
        assert state["calls"][0]["model"] == "openai/gpt-4o"

    async def test_ollama_provider_prefixes_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No env required.
        state = _patch_litellm(
            monkeypatch, lambda **kw: _make_success_response()  # noqa: ARG005
        )
        adapter = _make_adapter(_make_config(provider="ollama", model="llama3"))
        req = CompletionRequest(messages=[Message(role="user", content="hi")])
        await adapter.complete(req)
        assert state["calls"][0]["model"] == "ollama/llama3"


# ---------------------------------------------------------------------------
# estimate_tokens
# ---------------------------------------------------------------------------


def test_estimate_tokens_returns_at_least_1(anthropic_env: None) -> None:  # noqa: ARG001
    adapter = _make_adapter()
    assert adapter.estimate_tokens([Message(role="user", content="")]) == 1


def test_estimate_tokens_scales_with_chars(anthropic_env: None) -> None:  # noqa: ARG001
    adapter = _make_adapter()
    short = [Message(role="user", content="x" * 4)]
    long_ = [Message(role="user", content="x" * 400)]
    assert adapter.estimate_tokens(long_) > adapter.estimate_tokens(short)


def test_estimate_tokens_counts_content_parts(anthropic_env: None) -> None:  # noqa: ARG001
    adapter = _make_adapter()
    msg = Message(
        role="user",
        content=[
            ContentPart(type="text", data="hello world"),
            ContentPart(type="image", data={"url": "x"}),
        ],
    )
    # 11 chars of text ~ 2 tokens
    assert adapter.estimate_tokens([msg]) >= 1


# ---------------------------------------------------------------------------
# FakeLlmAdapter
# ---------------------------------------------------------------------------


class TestFakeAdapter:
    async def test_pops_responses_in_order(self) -> None:
        r1 = CompletionResult(
            text="one",
            tool_calls=(),
            finish_reason="stop",
            usage=TokenUsage(1, 1, 0, 0),
            model="x",
            cached_prefix_tokens=0,
            elapsed_ms=1,
        )
        r2 = CompletionResult(
            text="two",
            tool_calls=(),
            finish_reason="stop",
            usage=TokenUsage(2, 2, 0, 0),
            model="x",
            cached_prefix_tokens=0,
            elapsed_ms=1,
        )
        fake = FakeLlmAdapter(scripted_responses=[r1, r2])
        req = CompletionRequest(messages=[Message(role="user", content="hi")])
        assert (await fake.complete(req)).text == "one"
        assert (await fake.complete(req)).text == "two"
        assert len(fake.calls) == _TWO_CALLS

    async def test_empty_script_raises(self) -> None:
        fake = FakeLlmAdapter(scripted_responses=[])
        req = CompletionRequest(messages=[Message(role="user", content="hi")])
        with pytest.raises(RuntimeError, match="no scripted_responses"):
            await fake.complete(req)

    async def test_assert_all_consumed_raises_if_unused(self) -> None:
        r1 = CompletionResult(
            text="x",
            tool_calls=(),
            finish_reason="stop",
            usage=TokenUsage(0, 0, 0, 0),
            model="x",
            cached_prefix_tokens=0,
            elapsed_ms=0,
        )
        fake = FakeLlmAdapter(scripted_responses=[r1])
        with pytest.raises(AssertionError):
            fake.assert_all_consumed()

    async def test_assert_all_consumed_passes_when_script_exhausted(self) -> None:
        r1 = CompletionResult(
            text="x",
            tool_calls=(),
            finish_reason="stop",
            usage=TokenUsage(0, 0, 0, 0),
            model="x",
            cached_prefix_tokens=0,
            elapsed_ms=0,
        )
        fake = FakeLlmAdapter(scripted_responses=[r1])
        req = CompletionRequest(messages=[Message(role="user", content="hi")])
        await fake.complete(req)
        fake.assert_all_consumed()

    async def test_stream_pops_chunk_list(self) -> None:
        chunks = [StreamChunk(delta_text="a"), StreamChunk(delta_text="b", finish_reason="stop")]
        fake = FakeLlmAdapter(scripted_streams=[chunks])
        req = CompletionRequest(messages=[Message(role="user", content="hi")], stream=True)
        collected = [c async for c in fake.stream(req)]
        assert len(collected) == _TWO_CHUNKS


# ---------------------------------------------------------------------------
# Tool-call round-trip (string JSON args → dict)
# ---------------------------------------------------------------------------


class TestToolCallParsing:
    async def test_parses_json_arguments_into_dict(
        self, anthropic_env: None, monkeypatch: pytest.MonkeyPatch  # noqa: ARG002
    ) -> None:
        cfg = _make_config(caps_overrides={"tool_use": "basic"})

        def impl(**_kw: Any) -> Any:
            return _make_success_response(
                tool_calls=[
                    {
                        "id": "tool_1",
                        "function": {
                            "name": "calc",
                            "arguments": '{"x": 1, "y": 2}',
                        },
                    }
                ],
                finish_reason="tool_calls",
            )

        _patch_litellm(monkeypatch, impl)
        adapter = _make_adapter(cfg)
        req = CompletionRequest(
            messages=[Message(role="user", content="hi")],
            tools=(Tool(name="calc", description="d", input_schema={}),),
        )
        result = await adapter.complete(req)
        assert len(result.tool_calls) == 1
        tc: ToolCall = result.tool_calls[0]
        assert tc.id == "tool_1"
        assert tc.name == "calc"
        assert tc.arguments == {"x": 1, "y": 2}

    async def test_malformed_json_arguments_raises(
        self, anthropic_env: None, monkeypatch: pytest.MonkeyPatch  # noqa: ARG002
    ) -> None:
        cfg = _make_config(caps_overrides={"tool_use": "basic"})

        def impl(**_kw: Any) -> Any:
            return _make_success_response(
                tool_calls=[
                    {
                        "id": "tool_1",
                        "function": {"name": "calc", "arguments": "not-json"},
                    }
                ],
                finish_reason="tool_calls",
            )

        _patch_litellm(monkeypatch, impl)
        adapter = _make_adapter(cfg)
        req = CompletionRequest(
            messages=[Message(role="user", content="hi")],
            tools=(Tool(name="calc", description="d", input_schema={}),),
        )
        with pytest.raises(LlmError) as excinfo:
            await adapter.complete(req)
        assert excinfo.value.args[0] == "malformed_tool_call"
