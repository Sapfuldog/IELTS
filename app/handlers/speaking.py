"""Speaking section: cue cards / questions, the learner replies by voice or text."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, or_f
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import keyboards as kb
from app.db import Database
from app.services import content
from app.states import Speaking

router = Router(name="speaking")


@router.message(or_f(Command("speaking"), F.text == kb.MENU_SPEAKING))
async def speaking_entry(message: Message, state: FSMContext) -> None:
    await state.clear()
    exercises = content.get_all("speaking")
    await message.answer(
        "🗣 <b>Speaking</b> — choose a part to practise:",
        reply_markup=kb.exercise_list("speaking", exercises),
    )


@router.callback_query(F.data.startswith("pick:speaking:"))
async def start_speaking(call: CallbackQuery, state: FSMContext) -> None:
    exercise_id = call.data.split(":", 2)[2]
    exercise = content.get_exercise("speaking", exercise_id)
    await call.answer()
    if not exercise:
        await call.message.answer("Sorry, that set is unavailable.")
        return

    await state.set_state(Speaking.answering)
    await state.update_data(exercise_id=exercise_id, q_index=0)

    await call.message.answer(
        f"🗣 <b>Part {exercise['part']}: {exercise['topic']}</b>\n\n"
        f"<i>{exercise['intro']}</i>"
    )
    if exercise.get("cue_card"):
        await call.message.answer(f"🃏 <b>Cue card</b>\n\n{exercise['cue_card']}")

    await _send_question(call.message, state)


async def _send_question(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    exercise = content.get_exercise("speaking", data["exercise_id"])
    idx = data["q_index"]
    total = len(exercise["questions"])
    q = exercise["questions"][idx]
    await message.answer(
        f"❓ <b>{idx + 1}/{total}</b>\n\n{q}\n\n"
        "🎙 Reply with a <b>voice message</b> (best practice) or type your answer."
    )


@router.callback_query(Speaking.answering, F.data == "flow:stop")
async def stop(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer("Stopped.")
    await state.clear()
    await call.message.answer("⏹ Stopped. Back to the menu.", reply_markup=kb.main_menu())


@router.message(Speaking.answering, F.voice | F.text | F.audio)
async def receive_answer(message: Message, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    exercise = content.get_exercise("speaking", data["exercise_id"])
    idx = data["q_index"]
    next_idx = idx + 1

    kind = "🎙 Voice answer received." if message.voice or message.audio else "📝 Answer noted."
    await message.answer(f"{kind} Good — keep your fluency going.")

    if next_idx < len(exercise["questions"]):
        await state.update_data(q_index=next_idx)
        await _send_question(message, state)
        return

    # Finished the set → deliver tips and close out.
    tips = "\n".join(f"• {t}" for t in exercise.get("tips", []))
    await db.save_result(
        user_id=message.chat.id,
        section="speaking",
        exercise_id=data["exercise_id"],
        score=None,
        max_score=None,
    )
    await state.clear()
    await message.answer(
        f"✅ <b>Part {exercise['part']} complete!</b>\n\n"
        f"<b>Examiner tips for this part</b>\n{tips}\n\n"
        "Re-record and compare, or try another part from the menu.",
        reply_markup=kb.main_menu(),
    )
