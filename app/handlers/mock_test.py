"""A full mock test: Listening → Reading → Writing → Speaking, then a band.

Listening and Reading are assembled from as many exercises as the bank can
supply towards a 40-question section, mirroring the real paper's four parts and
three passages. It is still a shortened sitting — the bank rarely reaches 40,
there is no clock, and Speaking is typed rather than spoken — but the shape is
right: four sections in order, no picking and choosing, a band for each and an
overall band at the end, scored the way IELTS scores.

The bands from the two quiz sections come off the conversion tables in
`app.services.banding`; Writing and Speaking are marked by the agent against
the band descriptors, and fall back to the rule-based estimator if the API is
unavailable, so a test always finishes with a score.
"""
from __future__ import annotations

import logging
import random
import time

from aiogram import F, Router
from aiogram.filters import Command, or_f
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import keyboards as kb
from app.config import Config
from app.db import Database
from app.formatting import esc, multi_prompt, split_message, spoiler
from app.services import banding, content, mistakes
from app.services.agent import TutorAgent
from app.services.evaluation import evaluate_essay
from app.services.grading import (
    CHOICE_TYPES,
    correct_answer_text,
    is_correct,
    normalize_choice,
)
from app.states import MockTest

logger = logging.getLogger(__name__)

router = Router(name="mock_test")

# The order is fixed — that is what makes it a test rather than a menu.
_STAGES = ("listening", "reading", "writing", "speaking")
_STAGE_STATE = {
    "listening": MockTest.listening,
    "reading": MockTest.reading,
    "writing": MockTest.writing,
    "speaking": MockTest.speaking,
}
# A real Listening or Reading paper is 40 questions. The bank is not that deep
# yet, so a section takes whatever it can reach — assemble_section stops early
# rather than repeating an exercise.
TARGET_QUESTIONS = 40

# The real allowances, in minutes. Speaking is 11-14 minutes spoken; typed
# answers take longer, so it is not compared against the clock.
TIME_LIMITS = {"listening": 30, "reading": 60, "writing": 60}


def _format_minutes(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes} min {secs:02d} s" if minutes else f"{secs} s"


def _timing_note(section: str, seconds: float) -> str:
    """How the learner's pace compares with the real allowance.

    Reported rather than enforced: a section cut off mid-answer teaches
    nothing, while knowing you took twice the allowance is exactly the
    feedback that changes how someone practises.
    """
    spent = _format_minutes(seconds)
    limit = TIME_LIMITS.get(section)
    if limit is None:
        return f"took {spent}"
    minutes = seconds / 60
    if minutes <= limit:
        return f"took {spent} of the {limit} min allowed ✅"
    return f"took {spent} — over the {limit} min allowed ⏰"


def _exercise_at(data: dict, section: str, index: int) -> dict | None:
    ids = data["picks"][section]
    if not 0 <= index < len(ids):
        return None
    return content.get_exercise(section, ids[index])


def _section_question_count(data: dict, section: str) -> int:
    return sum(
        len(content.get_exercise(section, eid).get("questions", []))
        for eid in data["picks"][section]
    )


_STAGE_TITLES = {
    "listening": "🎧 Section 1 — Listening",
    "reading": "📖 Section 2 — Reading",
    "writing": "✍️ Section 3 — Writing",
    "speaking": "🗣 Section 4 — Speaking",
}


# --- Entry ----------------------------------------------------------------

@router.message(or_f(Command("test"), F.text == kb.MENU_TEST))
async def test_entry(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "📝 <b>Full IELTS mock test</b>\n\n"
        "Four sections in order: Listening, Reading, Writing, Speaking.\n"
        "You will get a band for each one and an overall band at the end.\n\n"
        "It takes about 30–40 minutes. /cancel stops it at any point — "
        "an unfinished test is not scored.",
        reply_markup=kb.start_test(),
    )


@router.callback_query(F.data == "test:start")
async def start_test(
    call: CallbackQuery, state: FSMContext, config: Config, db: Database
) -> None:
    await call.answer()
    picks = _pick_exercises()
    missing = [s for s, items in picks.items() if not items]
    if missing:
        await call.message.answer(
            "❌ Cannot start: no exercises available for "
            f"{', '.join(missing)}. Add content and try again."
        )
        return

    await state.update_data(
        picks={s: [ex["id"] for ex in items] for s, items in picks.items()},
        stage_index=0,
        q_index=0,
        correct=0,
        bands={},
    )
    await _begin_stage(call.message, state, config, db)


def assemble_section(section: str, target: int = TARGET_QUESTIONS) -> list[dict]:
    """Draw exercises until the section has roughly `target` questions.

    A real paper is 40 questions per section. The bank rarely holds that in one
    exercise, so several are stacked — which is also what the real Listening
    and Reading papers do, four parts and three passages respectively.

    Exercises are never repeated inside one sitting: seeing the same passage
    twice would measure memory rather than reading.
    """
    pool = list(content.get_all(section))
    random.shuffle(pool)
    # Easiest first, as a real paper does: Reading passages get harder across
    # the three, and a candidate who meets the hardest text first loses time
    # they would have banked on the easy one. Exercises with no stated band
    # sit in the middle rather than being pushed to either end.
    pool.sort(key=lambda e: e.get("target_band") or 6)

    chosen: list[dict] = []
    questions = 0
    for exercise in pool:
        if questions >= target:
            break
        chosen.append(exercise)
        questions += len(exercise.get("questions", []))
    return chosen


def _pick_exercises() -> dict[str, list[dict]]:
    """The material for one sitting: several exercises for the quiz sections."""
    picks: dict[str, list[dict]] = {}
    for section in _STAGES:
        items = content.get_all(section)
        if section in ("listening", "reading"):
            picks[section] = assemble_section(section)
            continue
        if section == "speaking":
            # Part 2 gives the candidate something substantial to answer.
            part2 = [i for i in items if i.get("part") == 2]
            items = part2 or items
        picks[section] = [random.choice(items)] if items else []
    return picks


# --- Stage flow -----------------------------------------------------------

async def _begin_stage(
    message: Message, state: FSMContext, config: Config, db: Database
) -> None:
    data = await state.get_data()
    section = _STAGES[data["stage_index"]]
    exercise = _exercise_at(data, section, 0)

    await state.set_state(_STAGE_STATE[section])
    await state.update_data(
        q_index=0, ex_index=0, correct=0, answers=[], started_at=time.time()
    )

    total = _section_question_count(data, section)
    header = f"<b>{_STAGE_TITLES[section]}</b>"
    if total:
        parts = len(data["picks"][section])
        header += f"\n<i>{total} questions across {parts} part(s)</i>"
    await message.answer(header)

    if section in ("listening", "reading"):
        await _present_material(message, section, exercise)
        await _ask_question(message, state)
    elif section == "writing":
        await message.answer(
            f"<b>{esc(exercise['title'])}</b>\n\n{esc(exercise['prompt'])}\n\n"
            f"✏️ Write at least <b>{exercise['min_words']}</b> words and send it "
            "as one message."
        )
    else:
        await _present_speaking(message, exercise)


async def _present_material(message: Message, section: str, exercise: dict) -> None:
    await message.answer(f"<b>{esc(exercise['title'])}</b>")
    if section == "reading":
        for chunk in split_message(exercise["passage"]):
            await message.answer(esc(chunk))
        return

    # Listening: reuse the quiz engine's clip sender so a failed clip degrades
    # to the transcript here exactly as it does in practice mode.
    from app.handlers.quiz import _send_clip

    audio_text = exercise["audio_text"]
    if await _send_clip(message, audio_text):
        for chunk in split_message(audio_text):
            await message.answer(f"📄 <i>Скрипт (нажмите, чтобы открыть)</i>\n{spoiler(chunk)}")
    else:
        await message.answer("🎧 <i>(Audio unavailable — read the transcript instead.)</i>")
        for chunk in split_message(audio_text):
            await message.answer(esc(chunk))


async def _present_speaking(message: Message, exercise: dict) -> None:
    lines = [f"<b>{esc(exercise['topic'])}</b>"]
    if exercise.get("cue_card"):
        lines.append(f"\n{esc(exercise['cue_card'])}")
    for i, q in enumerate(exercise.get("questions", []), 1):
        lines.append(f"{i}. {esc(q)}")
    lines.append(
        "\n🗣 Answer in writing, as fully as you would speak — aim for 150–250 "
        "words. Send it as one message."
    )
    await message.answer("\n".join(lines))


def _current_question(data: dict, section: str) -> dict:
    exercise = _exercise_at(data, section, data["ex_index"])
    return exercise["questions"][data["q_index"]]


async def _ask_question(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    section = _STAGES[data["stage_index"]]
    q = _current_question(data, section)

    # Numbered across the whole section, as on a real answer sheet, so the
    # count does not restart at 1 with every new passage.
    asked = len(data.get("answers", [])) + 1
    total = _section_question_count(data, section)

    header = f"❓ <b>Question {asked}/{total}</b>\n\n{esc(q['q'])}"
    keyboard = kb.answer_keyboard(q)
    if keyboard:
        await message.answer(header, reply_markup=keyboard)
    elif q["type"] == "multi":
        await message.answer(f"{header}\n\n{multi_prompt(q)}")
    else:
        await message.answer(header + "\n\n✏️ <i>Type your answer:</i>")


async def _record_answer(
    message: Message, state: FSMContext, config: Config, db: Database, given: str
) -> None:
    """Score one quiz answer. The test stays silent about right and wrong."""
    data = await state.get_data()
    section = _STAGES[data["stage_index"]]
    ex_index = data["ex_index"]
    exercise = _exercise_at(data, section, ex_index)
    q = exercise["questions"][data["q_index"]]

    was_right = is_correct(q, given)
    if not was_right and q["type"] == "gap":
        await mistakes.from_gap_answer(
            db, message.chat.id, q, given, origin_id=exercise["id"]
        )
    correct = data["correct"] + (1 if was_right else 0)
    # Kept so the review at the end of the section can show what was answered;
    # during the section itself the test stays silent about right and wrong.
    answers = [
        *data.get("answers", []),
        {"given": given, "right": was_right,
         "exercise_id": exercise["id"], "q_index": data["q_index"]},
    ]

    next_q = data["q_index"] + 1
    if next_q < len(exercise["questions"]):
        await state.update_data(correct=correct, q_index=next_q, answers=answers)
        await _ask_question(message, state)
        return

    # This part is done — move to the next one, if the section has more.
    next_ex = ex_index + 1
    await state.update_data(
        correct=correct, q_index=0, ex_index=next_ex, answers=answers
    )
    following = _exercise_at({**data, "picks": data["picks"]}, section, next_ex)
    if following is not None:
        await message.answer(
            f"➡️ <b>Part {next_ex + 1} of {len(data['picks'][section])}</b>"
        )
        await _present_material(message, section, following)
        await _ask_question(message, state)
        return

    await _send_review(message, section, data["picks"][section], answers)
    total = len(answers)
    band = banding.raw_to_band(section, correct, total)
    await _finish_stage(
        message, state, config, db, section, band,
        summary=f"{correct}/{total} correct",
    )


def _given_text(question: dict, given: str) -> str:
    """Render what the learner chose, not the raw callback payload."""
    if question["type"] == "mc":
        options = question.get("options", [])
        if given.isdigit() and 0 <= int(given) < len(options):
            return options[int(given)]
        return given or "—"
    if question["type"] in CHOICE_TYPES:
        return normalize_choice(given)
    return given.strip() or "—"


async def _send_review(
    message: Message, section: str, exercise_ids: list[str], answers: list[dict]
) -> None:
    """Go through the section question by question, once it is finished.

    Held back until the end on purpose: told immediately, the learner adjusts
    to the feedback and the remaining questions stop measuring anything.

    Each answer carries the exercise it belongs to, so a section built from
    several passages is reviewed in the order it was actually answered.
    """
    lines = ["📋 <b>Answers for this section</b>", ""]
    for i, record in enumerate(answers, 1):
        exercise = content.get_exercise(section, record["exercise_id"])
        if exercise is None:
            continue
        q = exercise["questions"][record["q_index"]]
        mark = "✅" if record["right"] else "❌"
        lines.append(f"{mark} <b>{i}.</b> {esc(q['q'])}")
        lines.append(f"    your answer: <i>{esc(_given_text(q, record['given']))}</i>")
        if not record["right"]:
            lines.append(f"    correct: <b>{esc(correct_answer_text(q))}</b>")
        if q.get("explanation"):
            lines.append(f"    <i>{esc(q['explanation'])}</i>")
        lines.append("")

    for chunk in split_message("\n".join(lines)):
        await message.answer(chunk)


async def _finish_stage(
    message: Message,
    state: FSMContext,
    config: Config,
    db: Database,
    section: str,
    band: float,
    summary: str,
) -> None:
    data = await state.get_data()
    bands = {**data["bands"], section: band}
    stage_index = data["stage_index"] + 1

    elapsed = time.time() - data.get("started_at", time.time())
    timings = {**data.get("timings", {}), section: elapsed}
    await state.update_data(bands=bands, stage_index=stage_index, timings=timings)

    await message.answer(
        f"✅ <b>{_STAGE_TITLES[section]} complete</b>\n"
        f"{esc(summary)} — band <b>{band}</b>\n"
        f"<i>{esc(_timing_note(section, elapsed))}</i>"
    )

    if stage_index < len(_STAGES):
        await _begin_stage(message, state, config, db)
    else:
        await _report(message, state, db)


# --- Quiz-section answers -------------------------------------------------

@router.callback_query(
    or_f(MockTest.listening, MockTest.reading), F.data.startswith("ans:")
)
async def on_test_choice(
    call: CallbackQuery, state: FSMContext, config: Config, db: Database
) -> None:
    await call.answer()
    await _record_answer(
        call.message, state, config, db, call.data.split(":", 1)[1]
    )


@router.message(or_f(MockTest.listening, MockTest.reading))
async def on_test_typed(
    message: Message, state: FSMContext, config: Config, db: Database
) -> None:
    data = await state.get_data()
    section = _STAGES[data["stage_index"]]
    q = _current_question(data, section)
    # Both gap and multi are answered by typing; everything else has buttons.
    if q["type"] not in ("gap", "multi"):
        await message.answer("Please tap one of the buttons above to answer.")
        return
    await _record_answer(message, state, config, db, message.text or "")


# --- Writing and Speaking -------------------------------------------------

@router.message(MockTest.writing)
async def on_test_essay(
    message: Message, state: FSMContext, config: Config, db: Database
) -> None:
    data = await state.get_data()
    task = content.get_exercise("writing", data["picks"]["writing"][0])
    await message.answer("⏳ Marking your essay…")

    agent = TutorAgent(config)
    result = await agent.evaluate("writing", task, message.text or "")
    if result is not None:
        for chunk in split_message(result.as_html()):
            await message.answer(chunk)
        await mistakes.from_corrections(
            db, message.chat.id, result.corrections, "writing", origin_id=task.get("id")
        )
        band = result.band
        summary = "marked against the band descriptors"
    else:
        # No API, or the call failed: fall back so the test still ends in a band.
        await message.answer(await evaluate_essay(message.text or "", task, config))
        band = _estimate_band(message.text or "", task)
        summary = "estimated from structure and length"

    await _finish_stage(message, state, config, db, "writing", band, summary)


@router.message(MockTest.speaking)
async def on_test_speaking(
    message: Message, state: FSMContext, config: Config, db: Database
) -> None:
    data = await state.get_data()
    task = content.get_exercise("speaking", data["picks"]["speaking"][0])
    await message.answer("⏳ Marking your answer…")

    agent = TutorAgent(config)
    result = await agent.evaluate("speaking", task, message.text or "")
    if result is not None:
        for chunk in split_message(result.as_html()):
            await message.answer(chunk)
        await mistakes.from_corrections(
            db, message.chat.id, result.corrections, "speaking", origin_id=task.get("id")
        )
        band = result.band
        summary = "marked against the band descriptors"
    else:
        band = _estimate_band(message.text or "", {"min_words": 150})
        await message.answer(
            "⚠️ <i>AI marking unavailable — this band is a rough estimate from "
            "length and range only.</i>"
        )
        summary = "estimated from length"

    await _finish_stage(message, state, config, db, "speaking", band, summary)


def _estimate_band(text: str, task: dict) -> float:
    """A deliberately crude stand-in used only when the API is unavailable.

    It measures length and lexical variety, which correlate with band but do
    not measure accuracy — the report says so rather than passing this off as
    a real mark.
    """
    words = text.split()
    if not words:
        return 0.0
    target = task.get("min_words", 250)
    variety = len({w.lower().strip(".,!?;:") for w in words}) / len(words)

    band = 4.0
    if len(words) >= target:
        band += 1.5
    elif len(words) >= target * 0.75:
        band += 0.75
    band += 1.5 if variety >= 0.6 else 0.75 if variety >= 0.45 else 0.0
    return banding.round_band(min(band, 7.0))


# --- Final report ---------------------------------------------------------

async def _report(message: Message, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    bands: dict[str, float] = data["bands"]
    overall = banding.overall_band(bands)

    await save_test_result(db, message.chat.id, bands)

    timings = data.get("timings", {})
    rows = "\n".join(
        f"{_STAGE_TITLES[s].split(' — ')[-1]:<10} <b>{bands[s]}</b>"
        + (f"  <i>({_format_minutes(timings[s])})</i>" if s in timings else "")
        for s in _STAGES
        if s in bands
    )
    parts = ["🎓 <b>Test complete</b>", "", rows, ""]
    if timings:
        # Keyed on having measured at all, not on the total being non-zero:
        # a fast clock tick can legitimately produce 0.0 seconds.
        parts.append(f"Total time: <b>{_format_minutes(sum(timings.values()))}</b>")
    parts += [
        f"<b>Overall band: {overall}</b>",
        f"<i>{esc(banding.describe(overall))}</i>",
        "",
        "This is a practice estimate from a shortened test, not an official "
        "IELTS result.",
    ]
    await message.answer("\n".join(parts), reply_markup=kb.main_menu())
    await state.clear()


async def save_test_result(db: Database, user_id: int, bands: dict[str, float]) -> None:
    """Store each section band plus the overall, so Progress can chart them."""
    for section, band in bands.items():
        await db.save_result(
            user_id=user_id, section=f"test:{section}",
            exercise_id=None, score=band, max_score=9.0,
        )
    await db.save_result(
        user_id=user_id, section="test:overall", exercise_id=None,
        score=banding.overall_band(bands), max_score=9.0,
    )
