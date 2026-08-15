"""The flashcard session, driven through the real handlers."""
from __future__ import annotations

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from app.handlers import vocabulary as vocab
from app.services import content

from conftest import FakeCallback, FakeMessage


@pytest.fixture
def state() -> FSMContext:
    return FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=1, user_id=1))


@pytest.fixture
def deck() -> dict:
    return content.get_all("vocabulary")[0]


class TestOpeningADeck:
    async def test_words_enter_the_collection(self, database, state, deck):
        message = FakeMessage()
        await vocab.start_deck(
            FakeCallback(message, f"pick:vocabulary:{deck['id']}"), state, database
        )
        counts = await database.card_counts(1)
        assert counts["total"] == len(deck["cards"])

    async def test_reopening_does_not_duplicate_or_reset(self, database, state, deck):
        message = FakeMessage()
        call = FakeCallback(message, f"pick:vocabulary:{deck['id']}")
        await vocab.start_deck(call, state, database)

        card = (await database.due_cards(1))[0]
        await database.record_review(card["id"], knew=True)

        await vocab.start_deck(call, state, database)
        assert (await database.card_counts(1))["total"] == len(deck["cards"])
        assert "already have every word" in message.joined()

    async def test_the_session_starts_on_the_front_of_a_card(self, database, state, deck):
        message = FakeMessage()
        await vocab.start_deck(
            FakeCallback(message, f"pick:vocabulary:{deck['id']}"), state, database
        )
        assert await state.get_state() == "Vocab:reviewing"
        assert "🃏" in message.joined()
        # The meaning must not be given away before the learner has recalled it.
        assert deck["cards"][0]["definition"] not in message.joined()


class TestReviewing:
    async def test_flipping_reveals_the_meaning(self, database, state, deck):
        message = FakeMessage()
        await vocab.start_deck(
            FakeCallback(message, f"pick:vocabulary:{deck['id']}"), state, database
        )
        await vocab.flip_card(FakeCallback(message, "card:flip"), state, database)
        assert deck["cards"][0]["definition"] in message.joined()

    async def test_a_known_card_leaves_the_session(self, database, state, deck):
        message = FakeMessage()
        await vocab.start_deck(
            FakeCallback(message, f"pick:vocabulary:{deck['id']}"), state, database
        )
        before = len((await state.get_data())["queue"])
        await vocab.grade_card(FakeCallback(message, "card:knew"), state, database)
        assert len((await state.get_data())["queue"]) == before - 1

    async def test_working_through_the_whole_deck_ends_the_session(
        self, database, state, deck
    ):
        message = FakeMessage()
        await vocab.start_deck(
            FakeCallback(message, f"pick:vocabulary:{deck['id']}"), state, database
        )
        for _ in range(len(deck["cards"]) + 2):
            if await state.get_state() is None:
                break
            await vocab.grade_card(FakeCallback(message, "card:knew"), state, database)

        assert await state.get_state() is None
        assert "Session finished" in message.joined()

    async def test_missed_cards_are_counted(self, database, state, deck):
        message = FakeMessage()
        await vocab.start_deck(
            FakeCallback(message, f"pick:vocabulary:{deck['id']}"), state, database
        )
        await vocab.grade_card(FakeCallback(message, "card:missed"), state, database)
        assert (await state.get_data())["missed"] == 1

    async def test_stopping_reports_progress(self, database, state, deck):
        message = FakeMessage()
        await vocab.start_deck(
            FakeCallback(message, f"pick:vocabulary:{deck['id']}"), state, database
        )
        await vocab.stop(FakeCallback(message, "flow:stop"), state, database)
        assert await state.get_state() is None
        assert "Session finished" in message.joined()


class TestMistakeCards:
    async def test_a_mistake_card_shows_where_it_came_from(self, database, state):
        await database.add_card(
            1, "breakfast", source="gap", origin_id="l1",
            context="The rate includes a continental breakfast.",
            learner_answer="brekfast",
        )
        message = FakeMessage()
        await vocab.start_review(FakeCallback(message, "card:start"), state, database)
        assert "из ошибки" in message.joined()

        await vocab.flip_card(FakeCallback(message, "card:flip"), state, database)
        assert "brekfast" in message.joined()

    async def test_a_mistake_card_can_be_retired(self, database, state):
        await database.add_card(1, "typo", source="writing", learner_answer="tpyo")
        message = FakeMessage()
        await vocab.start_review(FakeCallback(message, "card:start"), state, database)
        await vocab.dismiss_card(FakeCallback(message, "card:dismiss"), state, database)
        assert (await database.card_counts(1))["total"] == 0


class TestEmptyQueue:
    async def test_nothing_due_is_reported_as_success(self, database, state):
        message = FakeMessage()
        await vocab.start_review(FakeCallback(message, "card:start"), state, database)
        assert "Nothing is due" in message.joined()
        assert await state.get_state() is None

    async def test_the_menu_works_for_a_new_learner(
        self, database, state, offline_config
    ):
        message = FakeMessage()
        await vocab.vocab_entry(message, state, database, offline_config)
        assert "Vocabulary" in message.joined()

    async def test_the_generate_button_is_hidden_without_a_key(
        self, database, state, offline_config
    ):
        from app import keyboards as kb
        from app.services import content

        markup = kb.vocab_menu(0, content.get_all("vocabulary"), can_generate=False)
        labels = [b.text for row in markup.inline_keyboard for b in row]
        assert not any("new deck" in label for label in labels)
