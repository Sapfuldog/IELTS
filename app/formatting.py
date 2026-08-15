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


MULTI_LETTERS = "ABCDEFGH"


def gap_prompt(question: dict) -> str:
    """The typing instruction, with the word bank when the question offers one.

    Without the list on screen a learner has to guess the exact wording; with
    it the task is the one a real paper sets.
    """
    bank = question.get("bank")
    if not bank:
        return "✏️ <i>Type your answer:</i>"
    words = "   ".join(f"<code>{esc(word)}</code>" for word in bank)
    return f"{words}\n\n✏️ <i>Type one word from the list above:</i>"


def multi_prompt(question: dict) -> str:
    """Lettered options plus the instruction, for a choose-several question.

    The answer is typed, so the letters have to be on screen — without them
    the learner has nothing to type.
    """
    wanted = len(question.get("answer") or [])
    lines = [
        f"{MULTI_LETTERS[i]}. {esc(option)}"
        for i, option in enumerate(question.get("options", []))
    ]
    lines.append(
        f"\n✏️ <i>Choose {wanted} letters and send them together, e.g. "
        f"{MULTI_LETTERS[:wanted]}</i>"
    )
    return "\n".join(lines)
