"""Vocabulary flashcards with a flip / next flow."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, or_f
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app import keyboards as kb
from app.db import Database
from app.services import content
from app.states import Vocab

router = Router(name="vocabulary")


@router.message(or_f(Command("vocabulary"), F.text == kb.MENU_VOCAB))
async def vocab_entry(message: Message, state: FSMContext) -> None:
    await state.clear()
    sets = content.get_all("vocabulary")
    await message.answer(
        "🔤 <b>Vocabulary</b> — choose a set:",
        reply_markup=kb.exercise_list("vocabulary", sets),
    )


@router.callback_query(F.data.startswith("pick:vocabulary:"))
async def start_set(call: CallbackQuery, state: FSMContext) -> None:
    set_id = call.data.split(":", 2)[2]
    vset = content.get_exercise("vocabulary", set_id)
    await call.answer()
    if not vset:
        await call.message.answer("Sorry, that set is unavailable.")
        return
    await state.set_state(Vocab.reviewing)
    await state.update_data(set_id=set_id, index=0)
    await call.message.answer(f"🔤 <b>{vset['topic']}</b>")
    await _show_card(call.message, state, reveal=False)


async def _show_card(message: Message, state: FSMContext, reveal: bool) -> None:
    data = await state.get_data()
    vset = content.get_exercise("vocabulary", data["set_id"])
    cards = vset["cards"]
    idx = data["index"]
    card = cards[idx]
    text = f"🃏 <b>{idx + 1}/{len(cards)}</b>\n\n<b>{card['word']}</b>"
    if reveal:
        text += f"\n\n<i>{card['definition']}</i>\n\n💬 {card['example']}"
    await message.answer(text, reply_markup=kb.vocab_nav())


@router.callback_query(Vocab.reviewing, F.data == "vocab:flip")
async def flip(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await _show_card(call.message, state, reveal=True)


@router.callback_query(Vocab.reviewing, F.data == "vocab:next")
async def next_card(call: CallbackQuery, state: FSMContext, db: Database) -> None:
    data = await state.get_data()
    vset = content.get_exercise("vocabulary", data["set_id"])
    cards = vset["cards"]
    idx = data["index"] + 1
    await call.answer()

    if idx >= len(cards):
        await db.save_result(
            user_id=call.message.chat.id,
            section="vocabulary",
            exercise_id=data["set_id"],
            score=float(len(cards)),
            max_score=float(len(cards)),
        )
        await state.clear()
        await call.message.answer(
            f"✅ Reviewed all {len(cards)} cards in <b>{vset['topic']}</b>. "
            "Come back tomorrow to reinforce them!",
            reply_markup=kb.main_menu(),
        )
        return

    await state.update_data(index=idx)
    await _show_card(call.message, state, reveal=False)


@router.callback_query(Vocab.reviewing, F.data == "flow:stop")
async def stop(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer("Stopped.")
    await state.clear()
    await call.message.answer("⏹ Stopped. Back to the menu.", reply_markup=kb.main_menu())
