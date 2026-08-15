"""Shows the learner their accumulated practice statistics."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, or_f
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app import keyboards as kb
from app.db import Database

router = Router(name="progress")

_LABELS = {
    "reading": "📖 Reading",
    "listening": "🎧 Listening",
    "writing": "✍️ Writing",
    "speaking": "🗣 Speaking",
    "vocabulary": "🔤 Vocabulary",
    "test:listening": "📝 Test · Listening",
    "test:reading": "📝 Test · Reading",
    "test:writing": "📝 Test · Writing",
    "test:speaking": "📝 Test · Speaking",
    "test:overall": "🎓 Test · Overall band",
}


def _is_band(section: str) -> bool:
    """Two kinds of result share the results table and must not be mixed.

    Quiz sections store correct answers out of a question count, which adds up
    across attempts into a meaningful percentage. Writing, Speaking and the
    mock test store a band from 0-9, where summing is meaningless — three
    attempts at band 6 is not 18 out of 27.
    """
    return section in ("writing", "speaking") or section.startswith("test:")


def _describe_row(section: str, row: dict) -> str:
    label = _LABELS.get(section, section.title())
    attempts = row["attempts"]

    if _is_band(section):
        average = row["avg_score"]
        if average is None:
            return f"{label}: {attempts} attempt(s)"
        return f"{label}: {attempts} attempt(s) · average band <b>{average:.1f}</b>"

    if row["total_max"]:
        pct = row["total_score"] / row["total_max"] * 100
        return (
            f"{label}: {attempts} attempt(s) · "
            f"{int(row['total_score'])}/{int(row['total_max'])} correct ({pct:.0f}%)"
        )
    return f"{label}: {attempts} attempt(s)"


@router.message(or_f(Command("progress"), F.text == kb.MENU_PROGRESS))
async def show_progress(message: Message, state: FSMContext, db: Database) -> None:
    await state.clear()
    stats = await db.stats_by_section(message.chat.id)
    if not stats:
        await message.answer(
            "📊 No practice yet. Pick a section and complete an exercise — "
            "your progress will show up here.",
            reply_markup=kb.main_menu(),
        )
        return

    lines = ["📊 <b>Your progress</b>\n"]
    lines += [_describe_row(row["section"], row) for row in stats]

    cards = await db.card_counts(message.chat.id)
    if cards["total"]:
        line = (
            f"\n🃏 <b>Cards</b>: {cards['total']} total, "
            f"<b>{cards['due']}</b> due now, {cards['learned']} learned"
        )
        if cards["from_mistakes"]:
            line += f"\n    {cards['from_mistakes']} built from your own mistakes"
        lines.append(line)

    recent = await db.recent_results(message.chat.id, limit=5)
    if recent:
        lines.append("\n<b>Recent activity</b>")
        for r in recent:
            label = _LABELS.get(r["section"], r["section"].title())
            when = str(r["created_at"])[:16]
            if r["score"] is None:
                lines.append(f"• {label} — done ({when})")
            elif _is_band(r["section"]):
                lines.append(f"• {label} — band {r['score']:.1f} ({when})")
            elif r["max_score"]:
                lines.append(
                    f"• {label} — {int(r['score'])}/{int(r['max_score'])} ({when})"
                )
            else:
                lines.append(f"• {label} — done ({when})")

    await message.answer("\n".join(lines), reply_markup=kb.main_menu())
