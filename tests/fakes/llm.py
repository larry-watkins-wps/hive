"""In-memory :class:`LlmAdapter` fake for unit tests (plan Task 3.8 Step 1).

Mirrors :class:`region_template.llm_adapter.LlmAdapter`'s public surface so
tests can drop a :class:`FakeLlmAdapter` anywhere a real adapter is expected
(typically via ``ctx.llm`` in handler tests).

Contract:

- Construct with a list of :class:`CompletionResult` (and optionally
  :class:`StreamChunk` iterables). Each ``complete()`` call pops the next
  result in order.
- ``calls`` records every :class:`CompletionRequest` that was handled.
- If ``complete()`` is called more times than there are scripted responses,
  :class:`RuntimeError` is raised — misconfigured tests fail loudly.
- ``assert_all_consumed()`` raises if the script wasn't exhausted — lets a
  test declare "exactly N calls expected" without counting.
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from region_template.llm_adapter import (
    CompletionRequest,
    CompletionResult,
    Message,
    StreamChunk,
)

__all__ = ["FakeLlmAdapter"]


class FakeLlmAdapter:
    """Adapter fake that returns scripted responses.

    Typical usage::

        fake = FakeLlmAdapter(scripted_responses=[r1, r2])
        result_a = await fake.complete(req_a)  # returns r1
        result_b = await fake.complete(req_b)  # returns r2
        fake.assert_all_consumed()

    To script streaming, pass ``scripted_streams=[[chunk1, chunk2, ...], ...]``;
    each ``stream()`` call consumes one list.
    """

    scripted_responses: list[CompletionResult]
    scripted_streams: list[list[StreamChunk]]
    calls: list[CompletionRequest]

    def __init__(
        self,
        scripted_responses: list[CompletionResult] | None = None,
        scripted_streams: list[list[StreamChunk]] | None = None,
    ) -> None:
        self.scripted_responses = list(scripted_responses or [])
        self.scripted_streams = list(scripted_streams or [])
        self.calls = []

    # ------------------------------------------------------------------
    # Public API — same shape as LlmAdapter
    # ------------------------------------------------------------------

    async def complete(self, req: CompletionRequest) -> CompletionResult:
        self.calls.append(req)
        if not self.scripted_responses:
            raise RuntimeError(
                "FakeLlmAdapter.complete called but no scripted_responses remain"
            )
        return self.scripted_responses.pop(0)

    async def stream(
        self,
        req: CompletionRequest,
    ) -> AsyncIterator[StreamChunk]:
        self.calls.append(req)
        if not self.scripted_streams:
            raise RuntimeError(
                "FakeLlmAdapter.stream called but no scripted_streams remain"
            )
        chunks = self.scripted_streams.pop(0)
        for chunk in chunks:
            yield chunk

    def estimate_tokens(self, messages: Sequence[Message]) -> int:
        """Approximate token count — 4 chars/token, ignoring non-text parts."""
        total_chars = 0
        for m in messages:
            if isinstance(m.content, str):
                total_chars += len(m.content)
            else:
                for part in m.content:
                    if part.type == "text" and isinstance(part.data, str):
                        total_chars += len(part.data)
        return max(1, total_chars // 4)

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    def assert_all_consumed(self) -> None:
        """Raise if any scripted response / stream was left unused."""
        if self.scripted_responses:
            raise AssertionError(
                f"{len(self.scripted_responses)} scripted_responses left unused"
            )
        if self.scripted_streams:
            raise AssertionError(
                f"{len(self.scripted_streams)} scripted_streams left unused"
            )
