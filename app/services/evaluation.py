"""Essay evaluation for the Writing section.

If an Anthropic API key is configured, the essay is graded by Claude against
the IELTS band descriptors. Otherwise a transparent rule-based estimator gives
useful (if rougher) feedback so the bot is fully functional offline.
"""
from __future__ import annotations

import asyncio
import re

from app.config import Config


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
    from anthropic import AsyncAnthropic  # imported lazily

    client = AsyncAnthropic(api_key=config.anthropic_api_key)
    prompt = (
        "You are an experienced IELTS examiner. Grade the following "
        f"Writing Task {task.get('task', 2)} response.\n\n"
        f"PROMPT:\n{task['prompt']}\n\n"
        f"CANDIDATE RESPONSE:\n{text}\n\n"
        "Give: (1) an estimated band score 0-9 for each of the four criteria "
        "(Task Achievement, Coherence & Cohesion, Lexical Resource, "
        "Grammatical Range & Accuracy) and an overall band; (2) two concrete "
        "strengths; (3) three specific, actionable improvements with examples "
        "rewritten from the candidate's own text. Keep it under 300 words. "
        "Use plain text, no markdown headers."
    )
    message = await client.messages.create(
        model=config.anthropic_model,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    parts = [block.text for block in message.content if getattr(block, "type", "") == "text"]
    return "🤖 <b>AI examiner feedback</b>\n\n" + "\n".join(parts).strip()


async def evaluate_essay(text: str, task: dict, config: Config) -> str:
    if config.ai_enabled:
        try:
            return await _ai_feedback(text, task, config)
        except Exception as exc:  # network/key errors → graceful fallback
            fallback = _heuristic_feedback(text, task)
            return f"⚠️ AI feedback unavailable ({exc.__class__.__name__}).\n\n{fallback}"
    return await asyncio.to_thread(_heuristic_feedback, text, task)
