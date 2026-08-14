"""HTML formatting helpers for outgoing messages.

Everything the bot sends uses ParseMode.HTML, so any text taken from the
content files has to be escaped before it goes out — a stray '&' or '<' in an
exercise would otherwise break the message.
"""
from __future__ import annotations

from html import escape as _escape

# Telegram messages are capped at 4096 characters.
TELEGRAM_LIMIT = 4096

TRANSLATION_LABEL = "🇷🇺 Перевод"
TRANSCRIPT_LABEL = "📄 Скрипт"


def esc(text: str) -> str:
    """Escape &, < and > for Telegram's HTML parse mode."""
    return _escape(str(text), quote=False)


def spoiler(text: str) -> str:
    """Hidden text — the reader taps it to reveal."""
    return f"<tg-spoiler>{esc(text)}</tg-spoiler>"


def translation_block(text: str, label: str = TRANSLATION_LABEL) -> str:
    """A labelled, tap-to-reveal translation."""
    return f"{label} <i>(нажмите, чтобы открыть)</i>\n{spoiler(text)}"


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Split on paragraph boundaries so long passages stay sendable.

    Falls back to a hard cut only when a single paragraph exceeds the limit.
    """
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for para in text.split("\n\n"):
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        while len(para) > limit:
            chunks.append(para[:limit])
            para = para[limit:]
        current = para
    if current:
        chunks.append(current)
    return chunks
