"""Vocabulary: spaced-repetition flashcards.

Opening a deck copies its words into the learner's own collection, and from
then on the deck matters less than the schedule — cards come back when they
are due, mixed with cards built from mistakes made elsewhere in the bot.

The card is always shown front first. Turning it over immediately, which is
what the old flip-through flow effectively did, is re-reading rather than
recall, and re-reading is the part of studying that feels productive without
being so.
"""
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, or_f
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import keyboards as kb
from app.config import Config
from app.db import Database
from app.formatting import esc, spoiler
from app.services import content
from app.services.agent import TutorAgent
from app.states import Vocab

logger = logging.getLogger(__name__)

router = Router(name="vocabulary")

SESSION_SIZE = 20

_SOURCE_LABELS = {
    "gap": "из ошибки в упражнении",
    "writing": "из разбора вашего эссе",
    "speaking": "из разбора вашего ответа",
}


@router.message(or_f(Command("vocabulary"), F.text == kb.MENU_VOCAB))
async def vocab_entry(
    message: Message, state: FSMContext, db: Database, config: Config
) -> None:
    await state.clear()
    counts = await db.card_counts(message.chat.id)
    decks = content.get_all("vocabulary")

    lines = ["🔤 <b>Vocabulary</b>"]
    if counts["total"]:
        lines.append(
            f"\nYour collection: {counts['total']} card(s), "
            f"<b>{counts['due']}</b> due now, {counts['learned']} learned."
        )
        if counts["from_mistakes"]:
            lines.append(f"{counts['from_mistakes']} of them came from your own mistakes.")
    lines.append("\nReview what is due, or open a deck to add new words:")

    await message.answer(
        "\n".join(lines),
        reply_markup=kb.vocab_menu(
            counts["due"], decks, can_generate=TutorAgent(config).available
        ),
    )


@router.callback_query(F.data.startswith("pick:vocabulary:"))
async def start_deck(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    """Add a deck's words to the collection, then study whatever is due."""
    deck_id = call.data.split(":", 2)[2]
    deck = content.get_exercise("vocabulary", deck_id)
    await call.answer()
    if not deck:
        await call.message.answer("Sorry, that set is unavailable.")
        return

    added = 0
    for card in deck.get("cards", []):
        added += await db.add_card(
            call.message.chat.id,
            card["word"],
            source="deck",
            origin_id=deck_id,
            definition=card.get("definition"),
            example=card.get("example"),
            translation=card.get("translation"),
        )

    note = (
        f"Added {added} new word(s) from <b>{esc(deck['topic'])}</b>."
        if added
        else f"You already have every word from <b>{esc(deck['topic'])}</b>."
    )
    await call.message.answer(note)
    await _begin_session(call.message, state, db)


@router.callback_query(F.data == "card:start")
async def start_review(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    await call.answer()
    await _begin_session(call.message, state, db)


async def _begin_session(message: Message, state: FSMContext, db: Database) -> None:
    cards = await db.due_cards(message.chat.id, limit=SESSION_SIZE)
    if not cards:
        await state.clear()
        await message.answer(
            "✅ Nothing is due right now — that is the schedule working. "
            "Open a deck to add new words, or come back later.",
            reply_markup=kb.main_menu(),
        )
        return

    await state.set_state(Vocab.reviewing)
    await state.update_data(queue=[c["id"] for c in cards], done=0, missed=0)
    await _show_front(message, state, db)


async def _current_card(state: FSMContext, db: Database, chat_id: int) -> dict | None:
    data = await state.get_data()
    queue = data.get("queue") or []
    if not queue:
        return None
    # Re-read rather than cache: a card missed earlier in the session may have
    # been rescheduled, and the row is the single source of truth.
    for card in await db.due_cards(chat_id, limit=SESSION_SIZE * 2):
        if card["id"] == queue[0]:
            return card
    return None


async def _show_front(message: Message, state: FSMContext, db: Database) -> None:
    card = await _current_card(state, db, message.chat.id)
    if card is None:
        await _finish(message, state, db)
        return

    data = await state.get_data()
    position = data["done"] + 1
    total = data["done"] + len(data["queue"])
    text = [f"🃏 <b>{position}/{total}</b>", "", f"<b>{esc(card['word'])}</b>"]
    if card["source"] != "deck":
        text.append(f"<i>{_SOURCE_LABELS.get(card['source'], card['source'])}</i>")
    await message.answer("\n".join(text), reply_markup=kb.card_front())


@router.callback_query(Vocab.reviewing, F.data == "card:flip")
async def flip_card(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    await call.answer()
    card = await _current_card(state, db, call.message.chat.id)
    if card is None:
        await _finish(call.message, state, db)
        return

    lines = [f"<b>{esc(card['word'])}</b>"]
    if card["translation"]:
        lines.append(f"🇷🇺 {esc(card['translation'])}")
    if card["definition"]:
        lines.append(f"\n<i>{esc(card['definition'])}</i>")
    if card["example"]:
        lines.append(f"\n💬 {esc(card['example'])}")
    if card["learner_answer"]:
        lines.append(f"\n❌ You wrote: <i>{esc(card['learner_answer'])}</i>")
    if card["context"] and card["source"] == "gap":
        lines.append(f"📄 {spoiler(card['context'])}")

    await call.message.answer(
        "\n".join(lines),
        reply_markup=kb.card_back(can_dismiss=card["source"] != "deck"),
    )


@router.callback_query(Vocab.reviewing, F.data.in_({"card:knew", "card:missed"}))
async def grade_card(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    knew = call.data == "card:knew"
    await call.answer("✅" if knew else "Back into the rotation")

    data = await state.get_data()
    queue = list(data.get("queue") or [])
    if queue:
        await db.record_review(queue[0], knew=knew)
        queue.pop(0)
    await state.update_data(
        queue=queue,
        done=data["done"] + 1,
        missed=data["missed"] + (0 if knew else 1),
    )
    await _show_front(call.message, state, db)


@router.callback_query(Vocab.reviewing, F.data == "card:dismiss")
async def dismiss_card(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    await call.answer("Retired.")
    data = await state.get_data()
    queue = list(data.get("queue") or [])
    if queue:
        await db.dismiss_card(queue[0])
        queue.pop(0)
    await state.update_data(queue=queue)
    await _show_front(call.message, state, db)


async def _finish(message: Message, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    done, missed = data.get("done", 0), data.get("missed", 0)
    await state.clear()

    counts = await db.card_counts(message.chat.id)
    await message.answer(
        f"✅ <b>Session finished</b> — {done} card(s) reviewed, "
        f"{done - missed} known, {missed} to work on.\n\n"
        f"🃏 {counts['due']} card(s) still due, {counts['learned']} learned overall.",
        reply_markup=kb.main_menu(),
    )


@router.callback_query(Vocab.reviewing, F.data == "flow:stop")
async def stop(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    await call.answer("Stopped.")
    await _finish(call.message, state, db)
