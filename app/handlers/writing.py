"""Writing section: prompt → candidate essay → examiner feedback."""
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
from app.services.evaluation import evaluate_essay
from app.states import Writing

router = Router(name="writing")


@router.message(or_f(Command("writing"), F.text == kb.MENU_WRITING))
async def writing_entry(message: Message, state: FSMContext) -> None:
    await state.clear()
    tasks = content.get_all("writing")
    await message.answer(
        "✍️ <b>Writing</b> — choose a task:",
        reply_markup=kb.exercise_list("writing", tasks),
    )


@router.callback_query(F.data.startswith("pick:writing:"))
async def start_task(call: CallbackQuery, state: FSMContext) -> None:
    task_id = call.data.split(":", 2)[2]
    task = content.get_exercise("writing", task_id)
    await call.answer()
    if not task:
        await call.message.answer("Sorry, that task is unavailable.")
        return

    await state.set_state(Writing.awaiting_essay)
    await state.update_data(task_id=task_id)

    lines = [
        f"✍️ <b>Writing Task {task['task']}: {esc(task['title'])}</b>",
        f"<i>Minimum {task['min_words']} words.</i>",
        "",
        esc(task["prompt"]),
    ]
    # The instruction is set apart from the situation on purpose: answering the
    # topic instead of the question is what costs marks under Task Achievement.
    if task.get("question"):
        lines += ["", f"<b>❓ {esc(task['question'])}</b>"]
        if task.get("question_ru"):
            lines.append(f"🇷🇺 {spoiler(task['question_ru'])}")

    if task.get("must_cover"):
        lines += ["", "<b>A complete answer must cover</b>"]
        russian = task.get("must_cover_ru") or []
        for i, point in enumerate(task["must_cover"]):
            lines.append(f"▫️ {esc(point)}")
            if i < len(russian):
                lines.append(f"    {spoiler(russian[i])}")

    tips = "\n".join(f"• {esc(t)}" for t in task.get("tips", []))
    lines += [
        "",
        f"<b>Tips</b>\n{tips}",
        "",
        "When you're ready, send your full answer as one message. "
        "Send /cancel to stop.",
    ]
    for chunk in split_message("\n".join(lines)):
        await call.message.answer(chunk)

    if task.get("translation"):
        await call.message.answer(translation_block(task["translation"]))


@router.message(Writing.awaiting_essay, F.text)
async def receive_essay(
    message: Message, state: FSMContext, db: Database, config: Config
) -> None:
    data = await state.get_data()
    task = content.get_exercise("writing", data["task_id"])
    if task is None:
        await state.clear()
        await message.answer("Task expired. Please start again.", reply_markup=kb.main_menu())
        return

    thinking = await message.answer("⏳ Assessing your response…")

    # Go through the agent when it is available so the band can be stored;
    # evaluate_essay only hands back rendered HTML, which Progress cannot use.
    result = await TutorAgent(config).evaluate("writing", task, message.text)
    if result is not None:
        feedback, band = result.as_html(), result.band
        await mistakes.from_corrections(
            db, message.chat.id, result.corrections, "writing",
            origin_id=data["task_id"],
        )
    else:
        feedback, band = await evaluate_essay(message.text, task, config), None

    await db.save_result(
        user_id=message.chat.id,
        section="writing",
        exercise_id=data["task_id"],
        score=band,
        max_score=9.0 if band is not None else None,
    )
    await state.clear()

    await thinking.delete()
    chunks = split_message(feedback)
    for chunk in chunks[:-1]:
        await message.answer(chunk)
    await message.answer(chunks[-1], reply_markup=kb.main_menu())
