"""Reading & Listening quiz engine.

Both sections are 'passage/audio + questions', so they share one FSM flow.
Listening additionally sends a synthesized voice clip (or the transcript).
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, or_f
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app import keyboards as kb
from app.db import Database
from app.services import content, tts
from app.services.grading import correct_answer_text, is_correct
from app.states import Quiz

router = Router(name="quiz")

_SECTION_TITLES = {"reading": "📖 Reading", "listening": "🎧 Listening"}


# --- Section entry: show the list of exercises ----------------------------

async def open_section(message: Message, section: str) -> None:
    exercises = content.get_all(section)
    await message.answer(
        f"{_SECTION_TITLES[section]} — choose an exercise:",
        reply_markup=kb.exercise_list(section, exercises),
    )


@router.message(or_f(Command("reading"), F.text == kb.MENU_READING))
async def reading_entry(message: Message, state: FSMContext) -> None:
    await state.clear()
    await open_section(message, "reading")


@router.message(or_f(Command("listening"), F.text == kb.MENU_LISTENING))
async def listening_entry(message: Message, state: FSMContext) -> None:
    await state.clear()
    await open_section(message, "listening")


# --- Start a chosen exercise ----------------------------------------------

@router.callback_query(F.data.startswith("pick:reading:"))
async def start_reading(call: CallbackQuery, state: FSMContext) -> None:
    await _start(call, state, section="reading")


@router.callback_query(F.data.startswith("pick:listening:"))
async def start_listening(call: CallbackQuery, state: FSMContext) -> None:
    await _start(call, state, section="listening")


async def _start(call: CallbackQuery, state: FSMContext, section: str) -> None:
    exercise_id = call.data.split(":", 2)[2]
    exercise = content.get_exercise(section, exercise_id)
    await call.answer()
    if not exercise:
        await call.message.answer("Sorry, that exercise is unavailable.")
        return

    await state.set_state(Quiz.answering)
    await state.update_data(
        section=section, exercise_id=exercise_id, q_index=0, correct=0
    )

    await call.message.answer(f"<b>{exercise['title']}</b>")

    if section == "reading":
        await call.message.answer(exercise["passage"])
    else:  # listening
        await _send_listening(call.message, exercise)

    await _send_question(call.message, state)


async def _send_listening(message: Message, exercise: dict) -> None:
    audio_text = exercise["audio_text"]
    path = await tts.synthesize(audio_text)
    if path is not None:
        with path.open("rb") as fh:
            voice = BufferedInputFile(fh.read(), filename="clip.mp3")
        await message.answer_voice(
            voice,
            caption="🎧 Listen carefully. You can replay it before answering.",
        )
    else:
        await message.answer(
            "🎧 <i>(Audio unavailable — read the transcript instead. "
            "Install gTTS to hear it as speech.)</i>\n\n" + audio_text
        )


# --- Question rendering & answer checking ---------------------------------

async def _send_question(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    exercise = content.get_exercise(data["section"], data["exercise_id"])
    idx = data["q_index"]
    total = len(exercise["questions"])
    q = exercise["questions"][idx]
    header = f"❓ <b>Question {idx + 1}/{total}</b>\n\n{q['q']}"

    if q["type"] == "mc":
        await message.answer(header, reply_markup=kb.mc_options(q["options"]))
    elif q["type"] == "tf":
        await message.answer(header, reply_markup=kb.tf_options())
    elif q["type"] == "tfng":
        await message.answer(header, reply_markup=kb.tfng_options())
    elif q["type"] == "ynng":
        await message.answer(header, reply_markup=kb.ynng_options())
    else:  # gap fill
        await message.answer(header + "\n\n✏️ <i>Type your answer:</i>")


async def _grade(message: Message, state: FSMContext, db: Database, given: str) -> None:
    data = await state.get_data()
    exercise = content.get_exercise(data["section"], data["exercise_id"])
    idx = data["q_index"]
    q = exercise["questions"][idx]

    correct = is_correct(q, given)
    right = correct_answer_text(q)

    verdict = "✅ Correct!" if correct else f"❌ Not quite. Answer: <b>{right}</b>"
    explanation = q.get("explanation", "")
    await message.answer(f"{verdict}\n\n{explanation}".strip())

    new_correct = data["correct"] + (1 if correct else 0)
    next_idx = idx + 1
    await state.update_data(correct=new_correct, q_index=next_idx)

    if next_idx >= len(exercise["questions"]):
        await _finish(message, state, db)
    else:
        await _send_question(message, state)


async def _finish(message: Message, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    exercise = content.get_exercise(data["section"], data["exercise_id"])
    total = len(exercise["questions"])
    correct = data["correct"]

    await db.save_result(
        user_id=message.chat.id,
        section=data["section"],
        exercise_id=data["exercise_id"],
        score=float(correct),
        max_score=float(total),
    )
    await state.clear()

    pct = correct / total * 100
    emoji = "🏆" if pct == 100 else "👍" if pct >= 60 else "📚"
    await message.answer(
        f"{emoji} <b>Finished: {exercise['title']}</b>\n"
        f"Score: <b>{correct}/{total}</b> ({pct:.0f}%)\n\n"
        "Pick another exercise or a different section from the menu.",
        reply_markup=kb.main_menu(),
    )


# --- Inbound answers (only while a quiz is active) ------------------------

@router.callback_query(Quiz.answering, F.data.startswith("ans:"))
async def on_choice(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    given = call.data.split(":", 1)[1]
    await call.answer()
    await _grade(call.message, state, db, given)


@router.callback_query(Quiz.answering, F.data == "flow:stop")
async def on_stop(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer("Stopped.")
    await state.clear()
    await call.message.answer("⏹ Stopped. Back to the menu.", reply_markup=kb.main_menu())


@router.message(Quiz.answering)
async def on_typed_answer(message: Message, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    exercise = content.get_exercise(data["section"], data["exercise_id"])
    q = exercise["questions"][data["q_index"]]
    if q["type"] != "gap":
        await message.answer("Please tap one of the buttons above to answer.")
        return
    await _grade(message, state, db, message.text or "")
