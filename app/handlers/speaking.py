"""Speaking section: cue cards / questions, the learner replies by voice or text."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, or_f
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import keyboards as kb
from app.config import Config
from app.db import Database
from app.formatting import esc, spoiler, split_message, translation_block
from app.services import content, mistakes
from app.services.agent import TutorAgent
from app.services.banding import describe
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
    await state.update_data(exercise_id=exercise_id, q_index=0, given=[])

    await call.message.answer(
        f"🗣 <b>Part {exercise['part']}: {esc(exercise['topic'])}</b>\n\n"
        f"<i>{esc(exercise['intro'])}</i>"
    )
    if exercise.get("cue_card"):
        text = f"🃏 <b>Cue card</b>\n\n{esc(exercise['cue_card'])}"
        if exercise.get("cue_card_translation"):
            text += f"\n\n{translation_block(exercise['cue_card_translation'])}"
        await call.message.answer(text)

    await _send_question(call.message, state)


async def _send_question(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    exercise = content.get_exercise("speaking", data["exercise_id"])
    idx = data["q_index"]
    total = len(exercise["questions"])
    q = exercise["questions"][idx]
    text = f"❓ <b>{idx + 1}/{total}</b>\n\n{esc(q)}"
    translations = exercise.get("questions_translation") or []
    if idx < len(translations):
        text += f"\n🇷🇺 {spoiler(translations[idx])}"
    await message.answer(
        f"{text}\n\n"
        "🎙 Reply with a <b>voice message</b> (best practice) or type your answer."
    )


@router.callback_query(Speaking.answering, F.data == "flow:stop")
async def stop(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer("Stopped.")
    await state.clear()
    await call.message.answer("⏹ Stopped. Back to the menu.", reply_markup=kb.main_menu())


async def _analyse(
    message: Message, exercise: dict, question: str, answer: str, config: Config
) -> None:
    """Show what to improve in one answer. No band: see Evaluation.as_html."""
    agent = TutorAgent(config)
    if not agent.available:
        return

    notice = await message.answer("⏳ Analysing your answer…")
    # Only the question just asked goes in, so the advice is about this answer
    # rather than the set as a whole.
    task = {**exercise, "questions": [question]}
    result = await agent.evaluate("speaking", task, answer)
    if result is None:
        await notice.edit_text(
            "⚠️ <i>Could not analyse that answer — see the bot log for why.</i>"
        )
        return

    await notice.delete()
    html = result.as_html("🗣 <b>How to improve this answer</b>", show_band=False)
    for chunk in split_message(html):
        await message.answer(chunk)


async def _band_for_set(
    message: Message, exercise: dict, answers: list[str], config: Config,
    db: Database | None = None, user_id: int | None = None,
) -> float | None:
    """One band for the whole set, judged on everything the learner said.

    IELTS marks a performance, not individual replies, so the score comes from
    a single pass over all the answers together rather than an average of
    per-answer numbers.
    """
    agent = TutorAgent(config)
    if not agent.available or not answers:
        return None

    transcript = "\n\n".join(
        f"Q: {q}\nA: {a}"
        for q, a in zip(exercise.get("questions", []), answers)
    )
    result = await agent.evaluate("speaking", exercise, transcript)
    if result is None:
        return None
    for chunk in split_message(
        result.as_html(f"📊 <b>Band for Part {exercise['part']}</b>")
    ):
        await message.answer(chunk)
    if db is not None and user_id is not None:
        await mistakes.from_corrections(
            db, user_id, result.corrections, "speaking", origin_id=exercise.get("id")
        )
    return result.band


@router.message(Speaking.answering, F.voice | F.text | F.audio)
async def receive_answer(
    message: Message, state: FSMContext, db: Database, config: Config
) -> None:
    data = await state.get_data()
    exercise = content.get_exercise("speaking", data["exercise_id"])
    idx = data["q_index"]
    next_idx = idx + 1
    given: list[str] = list(data.get("given", []))

    if message.text:
        given.append(message.text)
        await _analyse(
            message, exercise, exercise["questions"][idx], message.text, config
        )
    else:
        # The bot has no speech recognition, so a voice note cannot be marked.
        # Say so plainly rather than implying the answer was assessed.
        await message.answer(
            "🎙 Voice answer received — good practice for fluency.\n"
            "<i>Analysis needs text: send the same answer typed and it will be "
            "marked against the band descriptors.</i>"
        )

    if next_idx < len(exercise["questions"]):
        await state.update_data(q_index=next_idx, given=given)
        await _send_question(message, state)
        return

    # Finished the set → one band over everything said, tips, and close out.
    band = await _band_for_set(
        message, exercise, given, config, db, message.chat.id
    )
    tips = "\n".join(f"• {esc(t)}" for t in exercise.get("tips", []))
    await db.save_result(
        user_id=message.chat.id,
        section="speaking",
        exercise_id=data["exercise_id"],
        score=band,
        max_score=9.0 if band is not None else None,
    )
    await state.clear()

    header = f"✅ <b>Part {exercise['part']} complete!</b>"
    if band is not None:
        header += f"\n<i>{esc(describe(band))}</i>"
    await message.answer(
        f"{header}\n\n"
        f"<b>Examiner tips for this part</b>\n{tips}\n\n"
        "Re-record and compare, or try another part from the menu.",
        reply_markup=kb.main_menu(),
    )
