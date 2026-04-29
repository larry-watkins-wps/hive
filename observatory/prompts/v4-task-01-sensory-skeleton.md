# v4 Task 1 — Sensory module skeleton + Settings extension

You are implementing Task 1 of the observatory v4 plan. Read this prompt in full before touching any file. The spec is authoritative when prose conflicts.

## Your role

Implement Task 1 only. Do not start Task 2. Drive to a green test suite + clean ruff + a single commit, then stop.

## Working directory

`C:/repos/hive` (repo root). Use `C:/repos/hive/.venv/Scripts/python.exe` for `python` invocations (venv has pytest; system python does not).

Use forward slashes in paths and Unix shell syntax (this is bash on Windows). Never use `cd` in commands — paths are absolute.

## Spec excerpts (authoritative)

### §4.1 Module layout

```
observatory/sensory/
├── __init__.py
├── allowlist.py     # frozenset of permitted topics
├── errors.py        # ForbiddenTopicError, PublishFailedError
├── publisher.py     # aiomqtt write client; allowlist enforcement (Task 2)
└── routes.py        # FastAPI APIRouter; POST /sensory/text/in (Task 3)
```

(The observatory backend is a flat package at `observatory/`, not `observatory/observatory/` — Python imports are `from observatory.X import …`. The sensory module sits as a subpackage `observatory.sensory`.)

### §4.2 Allowlist

```python
# observatory/sensory/allowlist.py
from typing import FrozenSet

ALLOWED_PUBLISH_TOPICS: FrozenSet[str] = frozenset({
    "hive/external/perception",
})
```

### §4.5 Settings

`observatory/config.py::Settings` is a `@dataclass(frozen=True)` populated by `Settings.from_env()` reading `os.environ`. v4 extends it with three flat fields:

```python
chat_default_speaker: str = "Larry"
chat_publish_qos: int = 1
chat_text_max_length: int = 4000
```

Env vars (flat names, matching existing `OBSERVATORY_*` convention):
- `OBSERVATORY_CHAT_DEFAULT_SPEAKER`
- `OBSERVATORY_CHAT_PUBLISH_QOS`
- `OBSERVATORY_CHAT_TEXT_MAX_LENGTH`

## Existing-contract surface (already in repo)

`observatory/config.py` (read it before editing — short file):

```python
"""Observatory runtime configuration — env-var driven."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    """Raised when an observatory env var is present but malformed."""


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name}={raw!r} is not an integer") from exc


@dataclass(frozen=True)
class Settings:
    bind_host: str = "127.0.0.1"
    bind_port: int = 8765
    hive_repo_root: Path = Path(".").resolve()
    max_ws_rate: int = 200
    mqtt_url: str = "mqtt://127.0.0.1:1883"
    regions_root: Path = Path("regions")
    ring_buffer_size: int = 10000

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            bind_host=os.environ.get("OBSERVATORY_BIND_HOST", cls.bind_host),
            bind_port=_int_env("OBSERVATORY_BIND_PORT", cls.bind_port),
            hive_repo_root=Path(
                os.environ.get("OBSERVATORY_HIVE_ROOT", str(Path(".").resolve()))
            ).resolve(),
            max_ws_rate=_int_env("OBSERVATORY_MAX_WS_RATE", cls.max_ws_rate),
            mqtt_url=os.environ.get("OBSERVATORY_MQTT_URL", cls.mqtt_url),
            regions_root=Path(
                os.environ.get("OBSERVATORY_REGIONS_ROOT", str(cls.regions_root))
            ),
            ring_buffer_size=_int_env("OBSERVATORY_RING_BUFFER_SIZE", cls.ring_buffer_size),
        )
```

`observatory/tests/unit/test_config.py` already exists with imports `pytest` and `from observatory.config import ConfigError, Settings` — append your new tests at the bottom of the file.

## Step-by-step

Do TDD: tests first, then implementation, expect-fail then expect-pass between.

### Step 1 — Create `observatory/sensory/` package + tests for allowlist/errors

Create these files exactly:

**`observatory/sensory/__init__.py`**
```python
"""Observatory sensory bridge — narrowly-scoped MQTT publisher.

This subpackage is the *only* part of observatory permitted to publish to
MQTT. Spec: observatory/docs/specs/2026-04-29-observatory-v4-chat-design.md.
"""
```

**`observatory/sensory/allowlist.py`**
```python
"""Topic allowlist — the boundary that keeps observatory's write surface narrow.

v4: only `hive/external/perception` (translator output for chat-typed input).
Future PRs add topics by editing this set + updating the v4 spec §4.2.
"""
from __future__ import annotations

ALLOWED_PUBLISH_TOPICS: frozenset[str] = frozenset({
    "hive/external/perception",
})
```

(Use `frozenset[str]` PEP 585 syntax rather than `FrozenSet` — the workspace ruff config has `target-version = "py311"` and `select = [..., "UP"]` which would flag `typing.FrozenSet` as UP035/UP006.)

**`observatory/sensory/errors.py`**
```python
"""Exceptions raised by the sensory bridge."""
from __future__ import annotations


class ForbiddenTopicError(Exception):
    """Raised when a publish call targets a topic outside the allowlist.

    This is a programming error — routes always build allowlist-permitted
    topics. If raised at runtime, the route returns HTTP 500.
    """

    def __init__(self, topic: str) -> None:
        self.topic = topic
        super().__init__(f"topic {topic!r} is not in the v4 publish allowlist")


class PublishFailedError(Exception):
    """Raised when the underlying aiomqtt publish call fails.

    Wraps the original `aiomqtt.MqttError` so route handlers can return
    HTTP 502 with the underlying message in the body.
    """

    def __init__(self, cause: Exception) -> None:
        self.cause = cause
        super().__init__(str(cause))
```

**`observatory/tests/unit/sensory/__init__.py`** — empty file.

**`observatory/tests/unit/sensory/test_allowlist.py`**
```python
"""Allowlist is the spec §4.2 boundary: exactly one topic for v4."""
from observatory.sensory.allowlist import ALLOWED_PUBLISH_TOPICS


def test_v4_allowlist_is_exactly_one_topic() -> None:
    """Spec §4.2: 'v4 = `hive/external/perception` only.'"""
    assert ALLOWED_PUBLISH_TOPICS == frozenset({"hive/external/perception"})


def test_allowlist_is_immutable() -> None:
    """Frozenset prevents accidental in-flight mutation by routes/tests."""
    assert isinstance(ALLOWED_PUBLISH_TOPICS, frozenset)
```

**`observatory/tests/unit/sensory/test_errors.py`**
```python
"""ForbiddenTopicError + PublishFailedError shape per spec §4.3-4.4."""
import aiomqtt

from observatory.sensory.errors import ForbiddenTopicError, PublishFailedError


def test_forbidden_topic_error_carries_topic() -> None:
    err = ForbiddenTopicError("hive/cognitive/pfc/oops")
    assert err.topic == "hive/cognitive/pfc/oops"
    assert "hive/cognitive/pfc/oops" in str(err)


def test_publish_failed_wraps_mqtt_error() -> None:
    """Spec §4.3: 'On aiomqtt.MqttError, raises PublishFailedError wrapping the original.'"""
    underlying = aiomqtt.MqttError("connection refused")
    err = PublishFailedError(underlying)
    assert err.cause is underlying
    assert "connection refused" in str(err)
```

### Step 2 — Run tests; expect green

```
C:/repos/hive/.venv/Scripts/python.exe -m pytest observatory/tests/unit/sensory/ -q
```

Expected: 4 passed.

### Step 3 — Extend `observatory/config.py`

Append the three new fields to the `Settings` dataclass *after* `ring_buffer_size: int = 10000`:

```python
    chat_default_speaker: str = "Larry"
    chat_publish_qos: int = 1
    chat_text_max_length: int = 4000
```

Inside `from_env()`, append to the `cls(...)` call (after the existing `ring_buffer_size=...` line):

```python
            chat_default_speaker=os.environ.get(
                "OBSERVATORY_CHAT_DEFAULT_SPEAKER", cls.chat_default_speaker
            ),
            chat_publish_qos=_int_env(
                "OBSERVATORY_CHAT_PUBLISH_QOS", cls.chat_publish_qos
            ),
            chat_text_max_length=_int_env(
                "OBSERVATORY_CHAT_TEXT_MAX_LENGTH", cls.chat_text_max_length
            ),
```

### Step 4 — Append config tests

Append to `observatory/tests/unit/test_config.py` (it already imports `pytest`, `ConfigError`, `Settings`):

```python
def test_chat_defaults() -> None:
    """Spec §4.5 + §8 default table."""
    s = Settings()
    assert s.chat_default_speaker == "Larry"
    assert s.chat_publish_qos == 1
    assert s.chat_text_max_length == 4000  # noqa: PLR2004 — spec literal


def test_chat_default_speaker_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OBSERVATORY_CHAT_DEFAULT_SPEAKER", "Operator")
    s = Settings.from_env()
    assert s.chat_default_speaker == "Operator"


def test_chat_publish_qos_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OBSERVATORY_CHAT_PUBLISH_QOS", "0")
    s = Settings.from_env()
    assert s.chat_publish_qos == 0


def test_chat_text_max_length_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OBSERVATORY_CHAT_TEXT_MAX_LENGTH", "2000")
    s = Settings.from_env()
    assert s.chat_text_max_length == 2000  # noqa: PLR2004 — env literal


def test_chat_publish_qos_invalid_raises_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OBSERVATORY_CHAT_PUBLISH_QOS", "not-a-number")
    with pytest.raises(ConfigError):
        Settings.from_env()
```

Add `# noqa: PLR2004` only when ruff complains about magic numbers; otherwise leave the assertion bare. The existing test file uses noqa comments for `8765`/`9000`/`42`, so follow that convention only where ruff actually flags.

### Step 5 — Run all unit tests

```
C:/repos/hive/.venv/Scripts/python.exe -m pytest observatory/tests/unit/ -q
```

Expected: all green (99 prior + 4 new sensory tests + ~5 new config tests).

### Step 6 — Lint

```
C:/repos/hive/.venv/Scripts/python.exe -m ruff check observatory/sensory/ observatory/tests/unit/sensory/ observatory/config.py observatory/tests/unit/test_config.py
```

Expected: clean. Fix any violations before committing.

### Step 7 — Commit (single commit for Task 1)

Stage exactly these paths and nothing else (the working tree has unrelated dirty files — the git status at session start showed M on `observatory/web-src/src/scene/Sparks.tsx`, several `regions/*` files, untracked region dirs; **none** of these are part of Task 1; do not stage them):

```
git add observatory/sensory/ observatory/tests/unit/sensory/ observatory/config.py observatory/tests/unit/test_config.py
```

Then commit using a HEREDOC. The Co-Authored-By trailer is required.

```
git commit -m "$(cat <<'EOF'
observatory(v4): sensory module skeleton + Settings chat fields

Adds observatory/sensory/ subpackage (allowlist + errors) and three flat
chat_* fields to Settings (default_speaker, publish_qos, text_max_length)
with OBSERVATORY_CHAT_* env overrides. No behaviour change yet — just the
boundary primitives Task 2's SensoryPublisher and Task 3's POST route
will plug into. Spec §4.1, §4.2, §4.5.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

If a pre-commit hook fails: investigate, fix, re-stage, create a NEW commit. Never `--amend` a hook-failed commit. Never `--no-verify`.

### Step 8 — Report

Report status as one of:
- `DONE` — tests pass, ruff clean, single commit landed. Include the commit SHA in your report (`git log -1 --oneline observatory/sensory/ observatory/config.py`).
- `DONE_WITH_CONCERNS` — same, plus a brief note about anything you flagged but didn't fix.
- `BLOCKED` — explain what specifically is blocking.

## Cumulative gotchas

- **Ruff config lives at workspace root `pyproject.toml`.** Do NOT add `[tool.ruff]` to `observatory/pyproject.toml`. The workspace ruff selects `["E","F","I","UP","B","SIM","PL"]`.
- **PEP 585 typing.** Use `frozenset[str]` not `typing.FrozenSet[str]` (UP035/UP006). The plan's verbatim code uses the older form — apply this drift correction.
- **`from __future__ import annotations`** at the top of every new `.py` (matches existing observatory style).
- **`PLR2004`** flags magic numbers in tests. Add `# noqa: PLR2004` only where ruff actually complains, and only with a brief reason (e.g. `# noqa: PLR2004 — spec literal`).
- **Use `C:/repos/hive/.venv/Scripts/python.exe`** for `python` invocations. The system python at `~\AppData\Local\Programs\Python\Python312\` does not have pytest.
- **Do not stage** files unrelated to Task 1 (the working tree had M flags on regions/*, observatory/web-src/scene/Sparks.tsx, etc. before you started — leave them alone).
- **Fully-qualify or alias `ConnectionError`** if you import from `region_template/errors.py` — it shadows the stdlib. Not relevant for this task but mentioned for completeness.

## Authority ordering

Spec > plan prose > biology > user instructions (user wins). If you find a spec/plan disagreement, follow the spec and note the discrepancy in your final report (do NOT silently improvise).

## Definition of done for Task 1

- [ ] `observatory/sensory/__init__.py`, `allowlist.py`, `errors.py` exist with the contents specified.
- [ ] `observatory/sensory/` only contains those three files (publisher.py and routes.py belong to Tasks 2/3 — do NOT pre-create them).
- [ ] `observatory/tests/unit/sensory/__init__.py`, `test_allowlist.py`, `test_errors.py` exist.
- [ ] `observatory/config.py` Settings has 3 new chat_* fields with defaults `"Larry"`, `1`, `4000`.
- [ ] `observatory/config.py::Settings.from_env()` reads the three env vars.
- [ ] `observatory/tests/unit/test_config.py` has 5 new tests (defaults + 3 env overrides + 1 malformed-int error).
- [ ] `python -m pytest observatory/tests/unit/ -q` is fully green.
- [ ] `python -m ruff check observatory/sensory/ observatory/tests/unit/sensory/ observatory/config.py observatory/tests/unit/test_config.py` is clean.
- [ ] Single commit landed with the exact message above.

Begin.
