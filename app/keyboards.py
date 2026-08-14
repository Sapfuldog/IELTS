"""Reusable keyboard builders."""
from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

# --- Main menu (persistent reply keyboard) --------------------------------

MENU_READING = "📖 Reading"
MENU_LISTENING = "🎧 Listening"
MENU_WRITING = "✍️ Writing"
MENU_SPEAKING = "🗣 Speaking"
MENU_VOCAB = "🔤 Vocabulary"
MENU_PROGRESS = "📊 Progress"


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=MENU_READING), KeyboardButton(text=MENU_LISTENING)],
            [KeyboardButton(text=MENU_WRITING), KeyboardButton(text=MENU_SPEAKING)],
            [KeyboardButton(text=MENU_VOCAB), KeyboardButton(text=MENU_PROGRESS)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Choose a section to practise…",
    )


# --- Exercise pickers -----------------------------------------------------

def exercise_list(section: str, exercises: list[dict]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for ex in exercises:
        label = ex.get("title") or ex.get("topic") or ex["id"]
        level = ex.get("level")
        if level:
            label = f"{label} · {level}"
        kb.button(text=label, callback_data=f"pick:{section}:{ex['id']}")
    kb.adjust(1)
    return kb.as_markup()


def mc_options(options: list[str]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    letters = ["A", "B", "C", "D", "E"]
    for i, opt in enumerate(options):
        kb.button(text=f"{letters[i]}. {opt}", callback_data=f"ans:{i}")
    kb.adjust(1)
    return kb.as_markup()


def tf_options() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ TRUE", callback_data="ans:TRUE")
    kb.button(text="❌ FALSE", callback_data="ans:FALSE")
    kb.adjust(2)
    return kb.as_markup()


def tfng_options() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ TRUE", callback_data="ans:TRUE")
    kb.button(text="❌ FALSE", callback_data="ans:FALSE")
    kb.button(text="❔ NOT GIVEN", callback_data="ans:NOT_GIVEN")
    kb.adjust(2, 1)
    return kb.as_markup()


def ynng_options() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ YES", callback_data="ans:YES")
    kb.button(text="❌ NO", callback_data="ans:NO")
    kb.button(text="❔ NOT GIVEN", callback_data="ans:NOT_GIVEN")
    kb.adjust(2, 1)
    return kb.as_markup()


def next_or_stop(next_label: str = "Next ▶️") -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text=next_label, callback_data="flow:next")
    kb.button(text="⏹ Stop", callback_data="flow:stop")
    kb.adjust(2)
    return kb.as_markup()


def reveal_answer() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="💡 Model answer / tips", callback_data="flow:next")
    kb.button(text="⏹ Stop", callback_data="flow:stop")
    kb.adjust(1)
    return kb.as_markup()


def vocab_nav() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🔁 Show meaning", callback_data="vocab:flip")
    kb.button(text="▶️ Next card", callback_data="vocab:next")
    kb.button(text="⏹ Stop", callback_data="flow:stop")
    kb.adjust(2, 1)
    return kb.as_markup()
