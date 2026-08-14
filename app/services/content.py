"""Loads exercise content from JSON files in app/content/."""
from __future__ import annotations

import json
from functools import lru_cache

from app.config import CONTENT_DIR


@lru_cache(maxsize=None)
def _load(name: str) -> list[dict]:
    path = CONTENT_DIR / f"{name}.json"
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def get_all(section: str) -> list[dict]:
    """Return every exercise for a section (reading, listening, ...)."""
    return _load(section)


def get_exercise(section: str, exercise_id: str) -> dict | None:
    for item in _load(section):
        if item["id"] == exercise_id:
            return item
    return None
