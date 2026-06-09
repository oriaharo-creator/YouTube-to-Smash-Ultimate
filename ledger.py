"""
Persistent record of which Smash Ultimate BGM slots have been modded.

Two ledgers are kept in parallel (so a record survives no matter how the user
later reorganises things):

* a **per-output-folder** manifest ``<output_dir>/modded_songs.json`` -- travels
  with the modpack, so the record stays next to the files it describes;
* a **global** history in the user's config directory -- survives across
  folders and sessions, and powers the "Modded songs" viewer.

Both are plain, human-readable JSON and deliberately have **no Qt dependency**,
so the CLI and the GUI share identical behaviour. A slot is keyed by its
``bgm_id``; recording the same slot again overwrites the previous entry (the
ledger reflects the *current* state of each slot, not an append-only log).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import List, Optional

MANIFEST_NAME = "modded_songs.json"
_SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------


def _global_dir() -> str:
    """Per-user config directory, following each OS's convention."""
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "yt2smash")


def global_ledger_path() -> str:
    return os.path.join(_global_dir(), MANIFEST_NAME)


def manifest_path(output_dir: str) -> str:
    return os.path.join(output_dir, MANIFEST_NAME)


# ---------------------------------------------------------------------------
# Entry model
# ---------------------------------------------------------------------------


@dataclass
class ModEntry:
    bgm_id: str
    name: str
    series: str
    internal_name: str
    filename: str
    mod_folder: str
    output_dir: str
    source_url: str
    uploaded: bool
    loop_start: int
    loop_end: int
    modded_at: str = ""  # ISO-8601 local time; filled in by :meth:`create`

    @classmethod
    def create(cls, **kwargs) -> "ModEntry":
        if not kwargs.get("modded_at"):
            kwargs["modded_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        return cls(**kwargs)


# ---------------------------------------------------------------------------
# Read / write
# ---------------------------------------------------------------------------


def _load_doc(path: str) -> dict:
    """Load a ledger document, tolerating a missing or corrupt file."""
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict) and isinstance(data.get("entries"), list):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"version": _SCHEMA_VERSION, "entries": []}


def _index(doc: dict) -> dict:
    return {e["bgm_id"]: e for e in doc.get("entries", []) if isinstance(e, dict) and "bgm_id" in e}


def load_entries(path: str) -> List[dict]:
    """Return all entries from a single ledger file (newest first if stored so)."""
    return _load_doc(path).get("entries", [])


def all_entries() -> List[dict]:
    """All entries from the global history, newest first."""
    return load_entries(global_ledger_path())


def find(bgm_id: str, output_dir: Optional[str] = None) -> Optional[dict]:
    """Return an existing entry for ``bgm_id``, or ``None``.

    The output-folder manifest is consulted first (it describes the files the
    user is about to overwrite); the global history is the fallback.
    """
    if output_dir:
        hit = _index(_load_doc(manifest_path(output_dir))).get(bgm_id)
        if hit:
            return hit
    return _index(_load_doc(global_ledger_path())).get(bgm_id)


def _upsert(path: str, entry: dict) -> None:
    """Insert or replace ``entry`` (keyed by bgm_id), writing atomically."""
    doc = _load_doc(path)
    kept = [e for e in doc.get("entries", []) if e.get("bgm_id") != entry["bgm_id"]]
    kept.append(entry)
    kept.sort(key=lambda e: e.get("modded_at", ""), reverse=True)
    doc["entries"] = kept
    doc["version"] = _SCHEMA_VERSION

    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def record(entry: ModEntry) -> None:
    """Write ``entry`` to both the per-folder manifest and the global history."""
    payload = asdict(entry)
    _upsert(manifest_path(entry.output_dir), payload)
    try:
        _upsert(global_ledger_path(), payload)
    except OSError:
        # The per-folder manifest is the source of truth; a failure to write the
        # convenience global history should never sink a successful conversion.
        pass
