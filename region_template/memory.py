"""Per-region memory store — spec §D.2 (STM), §D.3 (LTM), §D.4 (Index).

A :class:`MemoryStore` manages the region's on-disk memory tree:

::

    regions/<name>/memory/
    ├── stm.json                # §D.2.1 schema
    ├── index.json              # §D.4 postings list (rebuilt each sleep)
    └── ltm/
        ├── core/               # identity, relationships, lessons
        ├── episodes/           # temporal episodes
        ├── knowledge/          # semantic facts
        └── procedural/         # how-to notes

STM writes use atomic write-rename (``stm.json.tmp`` → ``stm.json``) serialized
by an :class:`asyncio.Lock`. TTL is pruned lazily on ``read_stm``/``list_stm``
and eagerly via ``sweep_expired``. Overflow handling follows §D.2.4 —
stage-1 trims the ``recent_events`` ring buffer when it dominates the budget,
and stage-2 raises :class:`~region_template.errors.StmOverflow`.

LTM methods (``write_ltm``, ``query_ltm``, ``build_index``) are gated with
:func:`region_template.capability.sleep_only` per §D.3.3.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from region_template.capability import sleep_only
from region_template.errors import StmOverflow
from shared.message_envelope import Envelope

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Value types (§D.2.2, §D.3.3, §D.6.1)
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class OriginRef:
    """Where a STM slot came from — topic, envelope id, correlation id."""

    topic: str | None = None
    envelope_id: str | None = None
    correlation_id: str | None = None


@dataclasses.dataclass(frozen=True)
class StmSlot:
    """One row out of the STM ``slots`` dict (§D.2.1)."""

    key: str
    value: Any
    written_at: str
    origin: OriginRef | None
    ttl_s: int | None
    tags: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class LtmMetadata:
    """Front-matter fields authored by the caller.

    ``created_at`` / ``updated_at`` are auto-managed by :meth:`write_ltm`.
    """

    topic: str
    tags: list[str]
    importance: float
    emotional_tag: str | None


@dataclasses.dataclass(frozen=True)
class LtmWriteResult:
    """Return shape of :meth:`write_ltm`."""

    path: str
    created: bool
    summary: str


@dataclasses.dataclass(frozen=True)
class MemoryQuery:
    """Shape of the `application/hive+memory-query` payload (§D.6.1)."""

    question: str
    topics: list[str]
    timeframe_hint: str | None
    max_results: int


@dataclasses.dataclass(frozen=True)
class MemoryHit:
    """One LTM match returned from :meth:`query_ltm`."""

    source: str
    content: str
    confidence: float
    emotional_tag: str | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_LTM_SUBDIRS: tuple[str, ...] = ("core", "episodes", "knowledge", "procedural")
_TERM_RE = re.compile(r"[a-z0-9]{3,}")


def _monotonic_now() -> float:
    """Wall-clock-independent clock used for TTL bookkeeping.

    Extracted as a module-level function so tests can monkeypatch it. We use
    :func:`time.monotonic` rather than :func:`time.time` because TTL is a
    relative duration; it must not skip when the system clock is adjusted.
    """
    return time.monotonic()


def _now_iso() -> str:
    """Wall-clock UTC timestamp in ISO-8601 with millisecond precision."""
    return (
        datetime.now(UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _validate_key(key: str) -> None:
    if not _KEY_RE.match(key):
        raise ValueError(
            f"STM key {key!r} must match {_KEY_RE.pattern} "
            "(lowercase, 1–64 chars, starts with a letter)"
        )


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# MemoryStore
# ---------------------------------------------------------------------------


class MemoryStore:
    """Per-region STM + LTM store.

    Construction creates the ``memory/`` tree if missing, quarantines an
    unparseable ``stm.json`` (see §D.10 failure-modes table), and loads the
    in-memory mirror of the STM document.
    """

    def __init__(
        self,
        root: Path,
        region_name: str,
        stm_max_bytes: int = 262_144,
        recent_events_max: int = 200,
        runtime: Any | None = None,
    ) -> None:
        self.root: Path = Path(root)
        self.region_name: str = region_name
        self.stm_max_bytes: int = stm_max_bytes
        self.recent_events_max: int = recent_events_max
        self._runtime: Any | None = runtime

        # Async serialization on STM writes (§D.2.2).
        self._lock = asyncio.Lock()

        # On-disk layout.
        _ensure_dir(self.root)
        _ensure_dir(self.root / "ltm")
        for sub in _LTM_SUBDIRS:
            _ensure_dir(self.root / "ltm" / sub)

        # In-memory STM mirror. Each slot carries a runtime-only ``_mono_at``
        # entry used for TTL arithmetic; that field is stripped before
        # serialization (see :meth:`_serialize`).
        self._stm: dict[str, Any] = self._load_stm()

    # ------------------------------------------------------------------
    # STM load / serialize
    # ------------------------------------------------------------------

    def _blank_state(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "region": self.region_name,
            "updated_at": _now_iso(),
            "slots": {},
            "recent_events": [],
        }

    def _load_stm(self) -> dict[str, Any]:
        stm_path = self.root / "stm.json"
        if not stm_path.exists():
            return self._blank_state()
        try:
            data = json.loads(stm_path.read_text(encoding="utf-8"))
            # Minimal shape check — full schema validation is advisory.
            if not isinstance(data, dict) or "slots" not in data:
                raise ValueError("stm.json missing required fields")
        except (json.JSONDecodeError, ValueError, OSError) as exc:
            # Quarantine per §D.10 and start fresh.
            ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
            quarantine = self.root / f"stm.json.corrupt.{ts}"
            # Best-effort rename; if we can't, at least we continue fresh.
            with contextlib.suppress(OSError):
                stm_path.rename(quarantine)
            log.warning(
                "stm_corrupt",
                region=self.region_name,
                error=str(exc),
                quarantine=str(quarantine),
            )
            return self._blank_state()

        # Attach runtime-only TTL bookkeeping. Each persisted slot carries
        # ``written_at`` (ISO-8601). On load we back-fill the monotonic
        # origin to "now", i.e. we restart the TTL countdown each process.
        # This is intentional — monotonic values don't survive restarts.
        now_mono = _monotonic_now()
        for slot in data.get("slots", {}).values():
            if isinstance(slot, dict) and slot.get("ttl_s") is not None:
                slot["_mono_at"] = now_mono

        # Ensure the recent_events key exists (it is optional in the schema).
        data.setdefault("recent_events", [])
        return data

    def _serialize(self) -> bytes:
        """Return a deterministic JSON serialization sans runtime-only keys."""
        state = {
            "schema_version": 1,
            "region": self.region_name,
            "updated_at": _now_iso(),
            "slots": {
                k: {kk: vv for kk, vv in slot.items() if not kk.startswith("_")}
                for k, slot in self._stm.get("slots", {}).items()
            },
            "recent_events": list(self._stm.get("recent_events", [])),
        }
        return json.dumps(state, ensure_ascii=False).encode("utf-8")

    async def _persist_locked(self) -> None:
        """Atomic write-rename of ``stm.json``. Caller must hold ``self._lock``."""
        payload = self._serialize()
        stm_path = self.root / "stm.json"
        tmp_path = self.root / "stm.json.tmp"
        tmp_path.write_bytes(payload)
        try:
            os.replace(str(tmp_path), str(stm_path))
        except OSError:
            # On failure the tmp file may be left behind; remove it if possible.
            with contextlib.suppress(OSError):
                tmp_path.unlink()
            raise

    # ------------------------------------------------------------------
    # TTL helpers
    # ------------------------------------------------------------------

    def _is_expired(self, slot: dict[str, Any]) -> bool:
        ttl = slot.get("ttl_s")
        if ttl is None:
            return False
        mono_at = slot.get("_mono_at")
        if mono_at is None:
            return False  # safety; pretend not expired
        return (_monotonic_now() - mono_at) > float(ttl)

    # ------------------------------------------------------------------
    # STM — public async API (§D.2.2)
    # ------------------------------------------------------------------

    async def write_stm(
        self,
        key: str,
        value: Any,
        origin: OriginRef | None = None,
        ttl_s: int | None = None,
        tags: list[str] | tuple[str, ...] = (),
    ) -> None:
        """Upsert a STM slot and persist atomically.

        Raises :class:`StmOverflow` if the size budget is exceeded and the
        stage-1 trim (§D.2.4) can't bring us back under.
        """
        _validate_key(key)
        async with self._lock:
            slot: dict[str, Any] = {
                "value": value,
                "written_at": _now_iso(),
                "origin": dataclasses.asdict(origin) if origin else {},
                "ttl_s": ttl_s,
                "tags": list(tags),
                # Runtime-only: stripped on serialize.
                "_mono_at": _monotonic_now() if ttl_s is not None else None,
            }
            prior_state = self._snapshot_stm()
            self._stm["slots"][key] = slot

            size = len(self._serialize())
            if size > self.stm_max_bytes:
                self._apply_overflow_policy(prior_state)

            await self._persist_locked()

    async def read_stm(self, key: str) -> StmSlot | None:
        """Return the slot for *key*, or ``None`` if missing or expired."""
        slots = self._stm.get("slots", {})
        slot = slots.get(key)
        if slot is None:
            return None
        if self._is_expired(slot):
            return None
        return _slot_to_dataclass(key, slot)

    async def list_stm(self, tag: str | None = None) -> list[StmSlot]:
        """Return all non-expired slots. Optionally filter by tag."""
        out: list[StmSlot] = []
        for key, slot in self._stm.get("slots", {}).items():
            if self._is_expired(slot):
                continue
            if tag is not None and tag not in slot.get("tags", []):
                continue
            out.append(_slot_to_dataclass(key, slot))
        return out

    async def delete_stm(self, key: str) -> bool:
        """Remove slot *key*. Returns True if it existed."""
        async with self._lock:
            slots = self._stm.get("slots", {})
            if key not in slots:
                return False
            del slots[key]
            await self._persist_locked()
            return True

    async def record_event(self, envelope: Envelope, summary: str) -> None:
        """Append an envelope summary to the recent_events ring buffer."""
        async with self._lock:
            events: list[dict[str, Any]] = self._stm.setdefault("recent_events", [])
            events.append(
                {
                    "envelope_id": envelope.id,
                    "topic": envelope.topic,
                    "ts": envelope.timestamp,
                    "summary": summary[:500],
                }
            )
            # Trim to the ring-buffer cap.
            overflow = len(events) - self.recent_events_max
            if overflow > 0:
                del events[:overflow]
            await self._persist_locked()

    async def recent_events(self) -> list[dict[str, Any]]:
        """Public read of the ring buffer — used by consolidation and tests."""
        return list(self._stm.get("recent_events", []))

    async def stm_size_bytes(self) -> int:
        """Return the serialized STM document size in bytes."""
        return len(self._serialize())

    async def sweep_expired(self) -> int:
        """Remove all expired slots from STM and persist. Returns removed count."""
        async with self._lock:
            slots = self._stm.get("slots", {})
            expired = [k for k, v in slots.items() if self._is_expired(v)]
            for k in expired:
                del slots[k]
            if expired:
                await self._persist_locked()
            return len(expired)

    # ------------------------------------------------------------------
    # Overflow policy (§D.2.4)
    # ------------------------------------------------------------------

    def _snapshot_stm(self) -> dict[str, Any]:
        """Deep-enough copy so we can roll back if stage-2 overflow fires."""
        return {
            "slots": {
                k: dict(slot) for k, slot in self._stm.get("slots", {}).items()
            },
            "recent_events": list(self._stm.get("recent_events", [])),
        }

    def _restore_snapshot(self, snapshot: dict[str, Any]) -> None:
        self._stm["slots"] = snapshot["slots"]
        self._stm["recent_events"] = snapshot["recent_events"]

    def _events_size_bytes(self) -> int:
        return len(
            json.dumps(self._stm.get("recent_events", []), ensure_ascii=False).encode(
                "utf-8"
            )
        )

    def _apply_overflow_policy(self, snapshot_if_rolled_back: dict[str, Any]) -> None:
        """Stage-1 trim, stage-2 raise per §D.2.4.

        Assumes the caller already added the offending slot and is holding
        ``self._lock``.
        """
        half_budget = self.stm_max_bytes // 2
        events_size = self._events_size_bytes()

        if events_size > half_budget:
            # Stage 1: trim oldest 50% of recent_events.
            events = self._stm.setdefault("recent_events", [])
            drop = len(events) // 2
            if drop > 0:
                del events[:drop]
                log.info(
                    "stm_overflow_trim",
                    region=self.region_name,
                    dropped=drop,
                    remaining=len(events),
                )
                # Re-check size; if still over, fall through to stage 2.
                if len(self._serialize()) <= self.stm_max_bytes:
                    return

        # Stage 2: roll back the offending write and raise.
        self._restore_snapshot(snapshot_if_rolled_back)
        raise StmOverflow(
            f"STM write exceeds stm_max_bytes={self.stm_max_bytes}"
        )

    # ------------------------------------------------------------------
    # LTM (§D.3) — gated to SLEEP phase
    # ------------------------------------------------------------------

    @sleep_only
    async def write_ltm(
        self,
        path: str,
        content: str,
        metadata: LtmMetadata,
        reason: str,
    ) -> LtmWriteResult:
        """Create or append to an LTM file.

        On create, a fresh YAML-ish front-matter header is written followed by
        a single dated section. On append, the new section is *prepended*
        ahead of the existing body (spec §D.3: "append-only by convention;
        actual writes use write_ltm which prepends a dated H2 section").

        ``reason`` is included in the structured log line and is intended for
        the eventual SleepCoordinator git-commit message.
        """
        self._reject_ltm_traversal(path)
        target = self.root / "ltm" / path
        _ensure_dir(target.parent)

        ts_header = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        section_header = "## " + _now_iso()
        new_section = f"{section_header}\n\n{content.strip()}\n"

        created: bool
        if target.exists():
            created = False
            existing = target.read_text(encoding="utf-8")
            fm_end = existing.find("---", 3)
            if not existing.startswith("---") or fm_end < 0:
                raise ValueError(
                    f"existing LTM file {path!r} has no front-matter delimiters"
                )
            old_fm = existing[3:fm_end]
            body = existing[fm_end + 3 :].lstrip("\n")
            fm_fields = _parse_frontmatter(old_fm)
            created_at = fm_fields.get("created_at", ts_header)
            new_fm = _render_frontmatter(
                metadata=metadata,
                created_at=created_at,
                updated_at=ts_header,
            )
            new_content = f"---\n{new_fm}---\n\n{new_section}\n{body}"
        else:
            created = True
            new_fm = _render_frontmatter(
                metadata=metadata,
                created_at=ts_header,
                updated_at=ts_header,
            )
            new_content = f"---\n{new_fm}---\n\n{new_section}"

        # Atomic write-rename for the LTM file.
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(new_content, encoding="utf-8")
        os.replace(str(tmp), str(target))

        log.info(
            "ltm_write",
            region=self.region_name,
            path=path,
            created=created,
            reason=reason,
        )
        return LtmWriteResult(path=path, created=created, summary=reason)

    def _reject_ltm_traversal(self, path: str) -> None:
        """Refuse paths that escape ``memory/ltm/``."""
        if path.startswith("/") or ".." in Path(path).parts or path.startswith("\\"):
            raise ValueError(f"illegal LTM path: {path!r}")

    @sleep_only
    async def query_ltm(self, q: MemoryQuery) -> list[MemoryHit]:
        """BM25-ish search over LTM. v0 scoring: sum(term_counts) * importance."""
        # Cheap scan — walks ltm/ and reads each file. For v0 with few files
        # this is adequate; post-v0 swaps in an embedding index.
        terms = _tokenize(q.question)
        if not terms:
            return []

        hits: list[MemoryHit] = []
        for md_path in _iter_markdown(self.root / "ltm"):
            rel = md_path.relative_to(self.root / "ltm").as_posix()
            text = md_path.read_text(encoding="utf-8")
            fm, body = _split_frontmatter(text)
            meta = _parse_frontmatter(fm)
            body_terms = _tokenize(body)
            counts: dict[str, int] = {}
            for t in body_terms:
                counts[t] = counts.get(t, 0) + 1

            score = sum(counts.get(t, 0) for t in terms)
            if score == 0:
                continue

            # Apply importance boost (keeps strict descending order stable).
            try:
                importance = float(meta.get("importance", 0.5))
            except (TypeError, ValueError):
                importance = 0.5

            # Topic boost: if the query topics match, add a small bump.
            topic_bump = 0.0
            doc_topic = meta.get("topic")
            if doc_topic and doc_topic in q.topics:
                topic_bump = 1.0

            confidence = float(score) * (0.5 + importance) + topic_bump

            hits.append(
                MemoryHit(
                    source=rel,
                    content=body.strip(),
                    confidence=confidence,
                    emotional_tag=meta.get("emotional_tag"),
                )
            )

        hits.sort(key=lambda h: h.confidence, reverse=True)
        return hits[: q.max_results]

    @sleep_only
    async def build_index(self) -> dict[str, Any]:
        """Walk ``ltm/`` and rebuild ``index.json`` per §D.4.

        Returns the index dict (also written to disk).
        """
        documents: dict[str, Any] = {}
        postings: dict[str, list[str]] = {}

        for md_path in _iter_markdown(self.root / "ltm"):
            rel = md_path.relative_to(self.root / "ltm").as_posix()
            text = md_path.read_text(encoding="utf-8")
            fm, body = _split_frontmatter(text)
            meta = _parse_frontmatter(fm)
            body_terms = _tokenize(body)
            counts: dict[str, int] = {}
            for t in body_terms:
                counts[t] = counts.get(t, 0) + 1

            try:
                importance = float(meta.get("importance", 0.5))
            except (TypeError, ValueError):
                importance = 0.5

            documents[rel] = {
                "tags": _parse_list(meta.get("tags", "[]")),
                "topic": meta.get("topic"),
                "created_at": meta.get("created_at"),
                "updated_at": meta.get("updated_at"),
                "importance": importance,
                "term_counts": counts,
            }
            for term in counts:
                postings.setdefault(term, []).append(rel)

        # Deterministic posting list ordering.
        for term_list in postings.values():
            term_list.sort()

        index = {
            "schema_version": 1,
            "built_at": _now_iso(),
            "documents": documents,
            "postings": postings,
        }

        index_path = self.root / "index.json"
        tmp = self.root / "index.json.tmp"
        tmp.write_text(
            json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(str(tmp), str(index_path))
        return index


# ---------------------------------------------------------------------------
# Internal conversion + parsing helpers
# ---------------------------------------------------------------------------


def _slot_to_dataclass(key: str, slot: dict[str, Any]) -> StmSlot:
    origin_dict = slot.get("origin") or {}
    origin = (
        OriginRef(
            topic=origin_dict.get("topic"),
            envelope_id=origin_dict.get("envelope_id"),
            correlation_id=origin_dict.get("correlation_id"),
        )
        if origin_dict
        else None
    )
    return StmSlot(
        key=key,
        value=slot["value"],
        written_at=slot["written_at"],
        origin=origin,
        ttl_s=slot.get("ttl_s"),
        tags=tuple(slot.get("tags", [])),
    )


def _render_frontmatter(
    metadata: LtmMetadata, created_at: str, updated_at: str
) -> str:
    tags_str = "[" + ", ".join(metadata.tags) + "]"
    emotional = metadata.emotional_tag if metadata.emotional_tag else "null"
    lines = [
        f"topic: {metadata.topic}",
        f"tags: {tags_str}",
        f"created_at: {created_at}",
        f"updated_at: {updated_at}",
        f"importance: {metadata.importance}",
        f"emotional_tag: {emotional}",
    ]
    return "\n".join(lines) + "\n"


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Extract simple ``key: value`` pairs from a YAML-ish header block.

    Not a full YAML parser — we only need the fields we write in
    :func:`_render_frontmatter`. Lists remain as strings (``"[a, b]"``) and
    are decoded on demand by :func:`_parse_list`.
    """
    out: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        out[k.strip()] = v.strip()
    return out


def _parse_list(value: str) -> list[str]:
    if not value:
        return []
    stripped = value.strip()
    if not (stripped.startswith("[") and stripped.endswith("]")):
        return [stripped]
    inner = stripped[1:-1].strip()
    if not inner:
        return []
    return [item.strip() for item in inner.split(",") if item.strip()]


def _split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---"):
        return "", text
    end = text.find("---", 3)
    if end < 0:
        return "", text
    fm = text[3:end]
    body = text[end + 3 :].lstrip("\n")
    return fm, body


def _tokenize(text: str) -> list[str]:
    return _TERM_RE.findall(text.lower())


def _iter_markdown(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*.md") if p.is_file())
