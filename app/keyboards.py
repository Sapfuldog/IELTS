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
MENU_TEST = "📝 Full test"


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=MENU_READING), KeyboardButton(text=MENU_LISTENING)],
            [KeyboardButton(text=MENU_WRITING), KeyboardButton(text=MENU_SPEAKING)],
            [KeyboardButton(text=MENU_VOCAB), KeyboardButton(text=MENU_PROGRESS)],
            [KeyboardButton(text=MENU_TEST)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Choose a section to practise…",
    )


# --- Exercise pickers -----------------------------------------------------

def exercise_list(
    section: str, exercises: list[dict], can_generate: bool = False
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for ex in exercises:
        label = ex.get("title") or ex.get("topic") or ex["id"]
        level = ex.get("level")
        if level:
            label = f"{label} · {level}"
        if ex.get("generated"):
            label = f"✨ {label}"
        kb.button(text=label, callback_data=f"pick:{section}:{ex['id']}")
    if can_generate:
        kb.button(text="✨ Write me a new one", callback_data=f"gen:{section}")
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


def start_test() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="▶️ Start the test", callback_data="test:start")
    kb.adjust(1)
    return kb.as_markup()


def answer_keyboard(question: dict) -> InlineKeyboardMarkup | None:
    """The right buttons for a question, or None when it must be typed."""
    builders = {
        "mc": lambda: mc_options(question["options"]),
        "tf": tf_options,
        "tfng": tfng_options,
        "ynng": ynng_options,
    }
    build = builders.get(question["type"])
    return build() if build else None


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


def card_front() -> InlineKeyboardMarkup:
    """Recall first, check second — turning it over immediately teaches nothing."""
    kb = InlineKeyboardBuilder()
    kb.button(text="🔁 Show the answer", callback_data="card:flip")
    kb.button(text="⏹ Stop", callback_data="flow:stop")
    kb.adjust(1)
    return kb.as_markup()


def card_back(can_dismiss: bool = False) -> InlineKeyboardMarkup:
    """Self-rating drives the schedule, so it is the only thing asked for."""
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ I knew it", callback_data="card:knew")
    kb.button(text="❌ I didn't", callback_data="card:missed")
    if can_dismiss:
        # Mistake cards are proposals: a typo is not a gap in knowledge.
        kb.button(text="🗑 Not worth studying", callback_data="card:dismiss")
    kb.button(text="⏹ Stop", callback_data="flow:stop")
    kb.adjust(2, 1, 1)
    return kb.as_markup()


def vocab_menu(
    due: int, decks: list[dict], can_generate: bool = False
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if due:
        kb.button(text=f"🔁 Review {due} card(s) due now", callback_data="card:start")
    for deck in decks:
        kb.button(
            text=deck.get("topic") or deck["id"],
            callback_data=f"pick:vocabulary:{deck['id']}",
        )
    if can_generate:
        kb.button(text="✨ Write me a new deck", callback_data="gen:vocabulary")
    kb.adjust(1)
    return kb.as_markup()
