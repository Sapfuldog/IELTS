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
from app.services import content, mistakes, transcription
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

    intro = f"🗣 <b>Part {exercise['part']}: {esc(exercise['topic'])}</b>\n\n<i>{esc(exercise['intro'])}</i>"
    if exercise.get("intro_ru"):
        intro += f"\n🇷🇺 {spoiler(exercise['intro_ru'])}"
    await call.message.answer(intro)
    if exercise.get("cue_card"):
        text = f"🃏 <b>Cue card</b>\n\n{esc(exercise['cue_card'])}"
        if exercise.get("cue_card_translation"):
            text += f"\n\n{translation_block(exercise['cue_card_translation'])}"
        await call.message.answer(text)
        # The real Part 2 is one minute to prepare and up to two to speak.
        # Saying so matters: candidates who have never practised the timing
        # either dry up after thirty seconds or are stopped mid-sentence.
        await call.message.answer(
            "⏱ <b>How Part 2 works in the exam</b>\n"
            "You get <b>1 minute</b> to make notes, then speak for "
            "<b>1–2 minutes</b> without interruption. Cover every bullet on "
            "the card, and keep going until the examiner stops you — running "
            "out of things to say early costs marks on Fluency.\n\n"
            f"🇷🇺 {spoiler('Одна минута на заметки, затем 1–2 минуты речи без остановки. Пройдите по всем пунктам карточки и говорите, пока вас не остановят: замолчать раньше времени — потеря баллов за беглость.')}"
        )

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


async def _transcribe_voice(message: Message, bot) -> str | None:
    """Turn a voice note into text, and show the learner what was heard.

    The transcript is always displayed. Speech recognition is least reliable
    on strongly accented English — which is precisely who this bot is for —
    so marking someone silently against a transcript they never saw would
    punish them for words the machine misheard.
    """
    if not transcription.available():
        await message.answer(
            "🎙 Voice received, but speech recognition is not installed here.\n"
            "<i>Send the same answer typed and it will be marked.</i>"
        )
        return None

    notice = await message.answer("🎧 Listening to your answer…")
    voice = message.voice or message.audio
    buffer = io.BytesIO()
    await bot.download(voice, destination=buffer)

    spoken = await asyncio.to_thread(transcription.transcribe, buffer.getvalue())
    if spoken is None or not spoken.text.strip():
        await notice.edit_text(
            "🎙 Could not make out the recording.\n"
            "<i>Try again somewhere quieter, or send the answer typed.</i>"
        )
        return None

    await notice.delete()
    lines = [
        "🎙 <b>What I heard</b>",
        "",
        f"<i>{esc(spoken.text)}</i>",
        "",
        "📊 " + "; ".join(spoken.observations()),
    ]
    if spoken.uncertain:
        # Say it plainly rather than marking a bad transcript as if it were
        # the answer.
        lines.append(
            "\n⚠️ <i>The recording was hard to make out, so the transcript "
            "may be wrong. If it does not match what you said, the feedback "
            "below is about the wrong words — send it typed instead.</i>"
        )
    await message.answer("\n".join(lines))
    return spoken.text


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
    message: Message, state: FSMContext, db: Database, config: Config, bot
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
        spoken = await _transcribe_voice(message, bot)
        if spoken:
            given.append(spoken)
            await _analyse(
                message, exercise, exercise["questions"][idx], spoken, config
            )

    if next_idx < len(exercise["questions"]):
        await state.update_data(q_index=next_idx, given=given)
        await _send_question(message, state)
        return

    # Finished the set → one band over everything said, tips, and close out.
    band = await _band_for_set(
        message, exercise, given, config, db, message.chat.id
    )
    # Each tip carries its Russian under a spoiler: advice a learner cannot
    # read is advice they cannot act on, but showing it unasked removes the
    # reading practice the English gives them.
    russian = exercise.get("tips_ru") or []
    tip_lines = []
    for i, tip in enumerate(exercise.get("tips", [])):
        tip_lines.append(f"• {esc(tip)}")
        if i < len(russian):
            tip_lines.append(f"   {spoiler(russian[i])}")
    tips = "\n".join(tip_lines)
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
