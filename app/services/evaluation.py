"""Essay evaluation for the Writing section.

If an Anthropic API key is configured, the essay is graded by Claude against
the IELTS band descriptors. Otherwise a transparent rule-based estimator gives
useful (if rougher) feedback so the bot is fully functional offline.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re

from app.config import Config

logger = logging.getLogger(__name__)


def _word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z']+", text))


def _heuristic_feedback(text: str, task: dict) -> str:
    words = _word_count(text)
    min_words = task.get("min_words", 250)
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    paragraphs = [p for p in text.split("\n") if p.strip()]
    linkers = [
        "however", "therefore", "furthermore", "moreover", "in addition",
        "consequently", "on the other hand", "for example", "for instance",
        "as a result", "in conclusion", "firstly", "secondly", "finally",
    ]
    lower = text.lower()
    used_linkers = sorted({l for l in linkers if l in lower})
    avg_sentence_len = words / max(len(sentences), 1)

    # Rough band estimate from a few measurable proxies (not an official score).
    band = 5.0
    if words >= min_words:
        band += 1.0
    elif words >= min_words * 0.8:
        band += 0.5
    if len(paragraphs) >= 4:
        band += 0.5
    if len(used_linkers) >= 4:
        band += 0.5
    elif len(used_linkers) >= 2:
        band += 0.25
    if 12 <= avg_sentence_len <= 22:
        band += 0.5
    band = min(band, 7.5)
    band = round(band * 2) / 2  # nearest 0.5

    lines = [
        "📝 <b>Rule-based feedback</b> (set ANTHROPIC_API_KEY for detailed AI scoring)\n",
        f"• Word count: <b>{words}</b> (target ≥ {min_words})"
        + ("  ✅" if words >= min_words else "  ⚠️ too short — you lose marks under the minimum"),
        f"• Paragraphs: <b>{len(paragraphs)}</b>"
        + ("  ✅" if len(paragraphs) >= 4 else "  ⚠️ aim for intro + 2 body + conclusion"),
        f"• Linking words used: <b>{len(used_linkers)}</b>"
        + (f" ({', '.join(used_linkers)})" if used_linkers else ""),
        f"• Average sentence length: <b>{avg_sentence_len:.0f}</b> words"
        + ("  ✅" if 12 <= avg_sentence_len <= 22 else "  ⚠️ vary short and long sentences"),
        f"\n<b>Estimated band (rough): {band}</b>",
        "\nThis estimate only checks structure and length. For grammar, vocabulary "
        "and argument quality, enable AI feedback.",
    ]
    return "\n".join(lines)


async def _ai_feedback(text: str, task: dict, config: Config) -> str:
    """Delegate to the agent, so there is one place that talks to a model."""
    from app.services.agent import TutorAgent  # imported lazily, avoids a cycle

    result = await TutorAgent(config).evaluate("writing", task, text)
    if result is None:
        raise RuntimeError("the marking call did not return a result")
    return result.as_html("🤖 <b>AI examiner feedback</b>")


def _explain(exc: Exception) -> str:
    """Short, actionable reason why the AI call failed."""
    name = exc.__class__.__name__
    detail = str(exc).strip() or "no details"
    hints = {
        "AuthenticationError": "check ANTHROPIC_API_KEY in .env (it must start with sk-ant-)",
        "PermissionDeniedError": "the API key has no access to this model",
        "NotFoundError": "check ANTHROPIC_MODEL in .env — that model id does not exist",
        "RateLimitError": "rate limit reached, try again in a minute",
        "APIConnectionError": "could not reach api.anthropic.com",
    }
    hint = hints.get(name)
    message = f"{name}: {detail[:200]}"
    if hint:
        message += f" — {hint}"
    return html.escape(message)


async def evaluate_essay(text: str, task: dict, config: Config) -> str:
    if config.ai_enabled:
        try:
            return await _ai_feedback(text, task, config)
        except Exception as exc:  # network/key errors → graceful fallback
            # Log the full traceback so the operator can see what actually broke.
            logger.warning("AI feedback failed, using rule-based fallback", exc_info=True)
            fallback = _heuristic_feedback(text, task)
            return f"⚠️ AI feedback unavailable — {_explain(exc)}\n\n{fallback}"
    return await asyncio.to_thread(_heuristic_feedback, text, task)
