"""Reading & Listening quiz engine.

Both sections are 'passage/audio + questions', so they share one FSM flow.
Listening additionally sends a synthesized voice clip (or the transcript).
"""
from __future__ import annotations

import logging
import random

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, or_f
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app import keyboards as kb
from app.config import Config
from app.db import Database
from app.formatting import (
    esc, gap_prompt, group_header, match_prompt, multi_prompt, spoiler,
    split_message, translation_block,
)
from app.services import content, mistakes, tts
from app.services.agent import TutorAgent
from app.services.grading import correct_answer_text, is_correct
from app.states import Quiz

logger = logging.getLogger(__name__)

router = Router(name="quiz")

_SECTION_TITLES = {"reading": "📖 Reading", "listening": "🎧 Listening"}


# --- Section entry: show the list of exercises ----------------------------

async def open_section(message: Message, section: str, config: Config) -> None:
    exercises = content.get_all(section)
    total, generated = content.count(section)
    suffix = f" ({total}, {generated} written for you)" if generated else f" ({total})"
    await message.answer(
        f"{_SECTION_TITLES[section]}{suffix} — choose an exercise:",
        reply_markup=kb.exercise_list(
            section, exercises, can_generate=TutorAgent(config).available
        ),
    )


_TOPICS = [
    "city life", "work and careers", "the environment", "technology",
    "education", "health and fitness", "travel", "food and cooking",
    "science", "art and culture", "money and shopping", "sport",
]


@router.callback_query(F.data.startswith("gen:"))
async def generate_exercise(call: CallbackQuery, config: Config) -> None:
    """Write a brand-new exercise and add it to the bank for good."""
    section = call.data.split(":", 1)[1]
    await call.answer("Writing a new exercise…")
    notice = await call.message.answer(
        f"✨ Writing a new {section} exercise — this takes 20–40 seconds…"
    )

    agent = TutorAgent(config)
    exercise = await agent.generate(section, topic=random.choice(_TOPICS))
    if exercise is None:
        await notice.edit_text(
            "❌ Could not write a new exercise just now — the existing ones are "
            "still there. Check the bot log for the reason."
        )
        return

    content.add_generated(section, exercise)
    await notice.edit_text(f"✅ Added: <b>{esc(exercise['title'])}</b>")
    await open_section(call.message, section, config)


@router.message(or_f(Command("reading"), F.text == kb.MENU_READING))
async def reading_entry(message: Message, state: FSMContext, config: Config) -> None:
    await state.clear()
    await open_section(message, "reading", config)


@router.message(or_f(Command("listening"), F.text == kb.MENU_LISTENING))
async def listening_entry(message: Message, state: FSMContext, config: Config) -> None:
    await state.clear()
    await open_section(message, "listening", config)


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

    await call.message.answer(f"<b>{esc(exercise['title'])}</b>")

    if section == "reading":
        await _send_reading(call.message, exercise)
    else:
        await _send_listening(call.message, exercise)

    await _send_question(call.message, state)


async def _send_translation(message: Message, exercise: dict) -> None:
    """Russian translation, hidden behind a spoiler so it never gives the text away."""
    translation = exercise.get("translation")
    if not translation:
        return
    for chunk in split_message(translation):
        await message.answer(translation_block(chunk))


async def _send_reading(message: Message, exercise: dict) -> None:
    for chunk in split_message(exercise["passage"]):
        await message.answer(esc(chunk))
    await _send_translation(message, exercise)


async def _send_listening(message: Message, exercise: dict) -> None:
    audio_text = exercise["audio_text"]
    if await _send_clip(message, audio_text):
        # The script would hand over the answers, so it stays hidden too —
        # available for checking, but only once the learner chooses to look.
        for chunk in split_message(audio_text):
            await message.answer(f"📄 <i>Скрипт (нажмите, чтобы открыть)</i>\n{spoiler(chunk)}")
    else:
        await message.answer(
            "🎧 <i>(Audio unavailable — read the transcript instead.)</i>"
        )
        for chunk in split_message(audio_text):
            await message.answer(esc(chunk))
    await _send_translation(message, exercise)


async def _send_clip(message: Message, audio_text: str) -> bool:
    """Send the synthesized clip. False means the caller should fall back to text.

    A clip that cannot be produced or delivered must not cost the learner the
    whole exercise: letting the error escape here would skip the transcript and
    the questions too, leaving the exercise looking simply broken.
    """
    path = await tts.synthesize(audio_text)
    if path is None:
        return False
    try:
        voice = BufferedInputFile(path.read_bytes(), filename="clip.mp3")
        await message.answer_voice(
            voice,
            caption="🎧 Listen carefully. You can replay it before answering.",
        )
        return True
    except TelegramAPIError as exc:
        # Telegram refuses sendVoice when the recipient has voice messages
        # switched off (VOICE_MESSAGES_FORBIDDEN), among other reasons.
        logger.warning("Could not send the listening clip: %s", exc)
        return False
    except OSError:
        logger.warning("Could not read the cached clip %s", path, exc_info=True)
        return False


# --- Question rendering & answer checking ---------------------------------

async def _send_question(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    exercise = content.get_exercise(data["section"], data["exercise_id"])
    idx = data["q_index"]
    total = len(exercise["questions"])
    q = exercise["questions"][idx]
    header = f"❓ <b>Question {idx + 1}/{total}</b>\n\n{esc(q['q'])}"

    intro = group_header(q)
    if intro:
        await message.answer(intro)

    if q["type"] == "match":
        await message.answer(f"{header}\n\n{match_prompt(q)}")
    elif q["type"] == "mc":
        await message.answer(header, reply_markup=kb.mc_options(q["options"]))
    elif q["type"] == "tf":
        await message.answer(header, reply_markup=kb.tf_options())
    elif q["type"] == "tfng":
        await message.answer(header, reply_markup=kb.tfng_options())
    elif q["type"] == "ynng":
        await message.answer(header, reply_markup=kb.ynng_options())
    elif q["type"] == "multi":
        await message.answer(f"{header}\n\n{multi_prompt(q)}")
    else:  # gap fill, with a word bank when the question offers one
        await message.answer(f"{header}\n\n{gap_prompt(q)}")


async def _grade(message: Message, state: FSMContext, db: Database, given: str) -> None:
    data = await state.get_data()
    exercise = content.get_exercise(data["section"], data["exercise_id"])
    idx = data["q_index"]
    q = exercise["questions"][idx]

    correct = is_correct(q, given)
    right = correct_answer_text(q)

    if not correct and q["type"] == "gap":
        # The learner's own errors are the best study material they have.
        await mistakes.from_gap_answer(
            db, message.chat.id, q, given, origin_id=data["exercise_id"]
        )

    verdict = "✅ Correct!" if correct else f"❌ Not quite. Answer: <b>{esc(right)}</b>"
    explanation = esc(q.get("explanation", ""))
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
        f"{emoji} <b>Finished: {esc(exercise['title'])}</b>\n"
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
    # Both gap and multi are answered by typing; everything else has buttons.
    if q["type"] not in ("gap", "multi", "match"):
        await message.answer("Please tap one of the buttons above to answer.")
        return
    await _grade(message, state, db, message.text or "")
