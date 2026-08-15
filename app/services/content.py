"""Loads exercise content: the shipped bank plus anything the agent generated.

Generated exercises live in DB_PATH's directory rather than app/content/, so
the two never get mixed up: app/content/ is curated and version-controlled,
data/generated/ grows at runtime and is disposable. Callers see one merged
list, which is why adding generation needed no changes in the handlers.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

from app.config import CONTENT_DIR

logger = logging.getLogger(__name__)

GENERATED_DIR = Path(os.getenv("DB_PATH", "data/ielts.db")).parent / "generated"

_lock = threading.Lock()
_cache: dict[str, list[dict]] = {}


def _read(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _load(section: str) -> list[dict]:
    """Shipped exercises first, generated ones after, cached until invalidated."""
    with _lock:
        if section in _cache:
            return _cache[section]

        items = _read(CONTENT_DIR / f"{section}.json")

        extra_path = GENERATED_DIR / f"{section}.json"
        if extra_path.exists():
            try:
                extra = _read(extra_path)
            except (OSError, json.JSONDecodeError):
                # A corrupt generated file must not take the whole section
                # down — the shipped bank is enough to keep practising.
                logger.warning("Ignoring unreadable %s", extra_path, exc_info=True)
                extra = []
            known = {item["id"] for item in items}
            items = items + [e for e in extra if e.get("id") not in known]

        _cache[section] = items
        return items


def get_all(section: str) -> list[dict]:
    """Return every exercise for a section (reading, listening, ...)."""
    return _load(section)


def get_exercise(section: str, exercise_id: str) -> dict | None:
    for item in _load(section):
        if item["id"] == exercise_id:
            return item
    return None


def count(section: str) -> tuple[int, int]:
    """(total, generated) — used by the menus to show how the bank is growing."""
    items = _load(section)
    return len(items), sum(1 for i in items if i.get("generated"))


def add_generated(section: str, exercise: dict) -> None:
    """Append a validated generated exercise and make it immediately visible.

    Callers must validate first (`app.services.validation`): nothing here
    checks the exercise, and a bad one would be persisted for good.
    """
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    path = GENERATED_DIR / f"{section}.json"
    with _lock:
        existing = _read(path) if path.exists() else []
        if any(e.get("id") == exercise["id"] for e in existing):
            return
        existing.append(exercise)
        # Write via a temporary file so an interrupted save cannot truncate a
        # bank the learner has been building up.
        tmp = path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(existing, fh, ensure_ascii=False, indent=2)
        tmp.replace(path)
        _cache.pop(section, None)
    logger.info("Added generated %s exercise %s", section, exercise["id"])


def reload() -> None:
    """Drop the cache — after editing content files by hand, or in tests."""
    with _lock:
        _cache.clear()
