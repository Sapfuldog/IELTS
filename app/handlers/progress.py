"""Shows the learner their accumulated practice statistics."""
from __future__ import annotations

from aiogram import F, Router
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
}


@router.message(F.text == kb.MENU_PROGRESS)
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
    for row in stats:
        label = _LABELS.get(row["section"], row["section"].title())
        attempts = row["attempts"]
        if row["total_max"]:
            pct = row["total_score"] / row["total_max"] * 100
            lines.append(
                f"{label}: {attempts} attempt(s) · "
                f"{int(row['total_score'])}/{int(row['total_max'])} correct ({pct:.0f}%)"
            )
        else:
            lines.append(f"{label}: {attempts} attempt(s)")

    recent = await db.recent_results(message.chat.id, limit=5)
    if recent:
        lines.append("\n<b>Recent activity</b>")
        for r in recent:
            label = _LABELS.get(r["section"], r["section"].title())
            if r["max_score"]:
                lines.append(f"• {label} — {int(r['score'])}/{int(r['max_score'])} ({r['created_at']})")
            else:
                lines.append(f"• {label} — done ({r['created_at']})")

    await message.answer("\n".join(lines), reply_markup=kb.main_menu())
