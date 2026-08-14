"""Optional text-to-speech for the Listening section.

Uses gTTS if it is installed; otherwise callers fall back to sending the
transcript as text. Generated files are cached on disk by content hash.
"""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

_CACHE_DIR = Path("media/tts")

try:  # gTTS is an optional dependency
    from gtts import gTTS  # type: ignore

    _AVAILABLE = True
except Exception:  # pragma: no cover - import guard
    _AVAILABLE = False


def is_available() -> bool:
    return _AVAILABLE


def _synthesize_sync(text: str) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    out = _CACHE_DIR / f"{digest}.mp3"
    if not out.exists():
        gTTS(text=text, lang="en").save(str(out))
    return out


async def synthesize(text: str) -> Path | None:
    """Return an mp3 Path for the text, or None if TTS is unavailable/failed."""
    if not _AVAILABLE:
        return None
    try:
        return await asyncio.to_thread(_synthesize_sync, text)
    except Exception:
        return None
