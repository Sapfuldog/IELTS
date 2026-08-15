"""Start, help, cancel and a catch-all fallback."""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app import keyboards as kb
from app.config import Config
from app.db import Database

# Global commands. Registered BEFORE the section routers so that /cancel and
# friends still work while an exercise has the user in an FSM state — those
# state handlers would otherwise swallow the command as an answer.
router = Router(name="common")

# The catch-all. Registered LAST, after every section router.
fallback_router = Router(name="fallback")

_WELCOME = (
    "👋 <b>Welcome to your IELTS prep coach!</b>\n\n"
    "Practise every part of the test right here:\n"
    "📖 <b>Reading</b> — passages with auto-checked questions\n"
    "🎧 <b>Listening</b> — audio clips + comprehension questions\n"
    "✍️ <b>Writing</b> — Task 1 & 2 prompts with examiner feedback\n"
    "🗣 <b>Speaking</b> — Parts 1-3 with cue cards and tips\n"
    "🔤 <b>Vocabulary</b> — flashcards for Band 7+\n"
    "📊 <b>Progress</b> — track how you're doing\n\n"
    "Tap a button below to begin. Send /help any time."
)

_HELP = (
    "ℹ️ <b>How to use the bot</b>\n\n"
    "Use the buttons under the message box, or these commands:\n"
    "/reading — 📖 passages with questions\n"
    "/listening — 🎧 audio with questions\n"
    "/writing — ✍️ essay tasks with feedback\n"
    "/speaking — 🗣 cue cards and questions\n"
    "/vocabulary — 🔤 flashcards\n"
    "/progress — 📊 your statistics\n"
    "/cancel — stop the current exercise\n\n"
    "• Reading/Listening: answer by tapping a button or typing.\n"
    "• Writing: send your essay as one message to get feedback.\n"
    "• Speaking: reply to each prompt with a voice message or text.\n\n"
    "Tip: set OPENROUTER_API_KEY (or ANTHROPIC_API_KEY) in .env for AI-graded "
    "Writing and Speaking feedback, and for exercises written on demand."
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, db: Database) -> None:
    await state.clear()
    user = message.from_user
    if user:
        await db.upsert_user(user.id, user.username, user.full_name)
    await message.answer(_WELCOME, reply_markup=kb.main_menu())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(_HELP, reply_markup=kb.main_menu())


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Cancelled. Back to the menu.", reply_markup=kb.main_menu())


@fallback_router.message()
async def fallback(message: Message) -> None:
    await message.answer(
        "I didn't catch that. Use the menu below or send /help.",
        reply_markup=kb.main_menu(),
    )
