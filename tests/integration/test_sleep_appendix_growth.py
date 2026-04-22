"""Integration: two consecutive sleep cycles grow rolling.md chronologically
while prompt.md stays byte-identical.

End-to-end assertion that the Append-Only Prompt Evolution surface (plan
Tasks 1-8) behaves correctly across consecutive cycles. Exercises
:meth:`SleepCoordinator.run` twice against a real :class:`AppendixStore`
on real disk, using the unit-test harness factory ``_build_coordinator``
because the surface being verified is filesystem-only — no MQTT, no
containers, no LLM calls beyond the scripted fake.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from tests.unit.test_sleep import (
    _build_coordinator,
    _completion,
    _review_json,
)

pytestmark = pytest.mark.integration


async def test_two_sleeps_produce_two_appendix_sections(tmp_path: Path) -> None:
    """Two successive sleep runs must append two dated H2 sections to
    rolling.md while prompt.md remains byte-identical across cycles."""
    first_entry = "first cycle insight about input-intent gaps"
    second_entry = "second cycle insight about sleep pressure"

    coord, runtime = _build_coordinator(
        tmp_path,
        scripted_llm_responses=[
            _completion(
                _review_json(
                    appendix_entry=first_entry,
                    reason="cycle one",
                )
            ),
            _completion(
                _review_json(
                    appendix_entry=second_entry,
                    reason="cycle two",
                )
            ),
        ],
    )

    prompt_path = runtime.region_root / "prompt.md"
    prompt_hash_before = hashlib.sha256(prompt_path.read_bytes()).hexdigest()

    result1 = await coord.run(trigger="explicit_request")
    assert result1.status == "committed_in_place"
    assert result1.sha is not None

    result2 = await coord.run(trigger="explicit_request")
    assert result2.status == "committed_in_place"
    assert result2.sha is not None
    assert result2.sha != result1.sha

    # prompt.md is byte-identical across both cycles — append-only evolution
    # lands in rolling.md, never touching the starter DNA.
    prompt_hash_after = hashlib.sha256(prompt_path.read_bytes()).hexdigest()
    assert prompt_hash_after == prompt_hash_before

    # rolling.md has exactly two dated H2 sections in chronological order.
    rolling_path = (
        runtime.region_root / "memory" / "appendices" / "rolling.md"
    )
    assert rolling_path.exists()
    rolling = rolling_path.read_text(encoding="utf-8")

    first_idx = rolling.index(first_entry)
    second_idx = rolling.index(second_entry)
    assert first_idx < second_idx, (
        f"Expected first entry before second in chronological order.\n"
        f"rolling.md:\n{rolling}"
    )

    h2_headers = [
        line for line in rolling.splitlines() if line.startswith("## ")
    ]
    _EXPECTED_H2_COUNT = 2
    assert len(h2_headers) == _EXPECTED_H2_COUNT, (
        f"Expected exactly two H2 sections, got {len(h2_headers)}:\n"
        f"{h2_headers}"
    )
    # Both headers carry the explicit_request trigger label (spec-level
    # convention: "## <iso> — <trigger>").
    for header in h2_headers:
        assert "explicit_request" in header, header

    # Tree is clean — both sleep commits landed cleanly.
    assert runtime.git.status_clean()
