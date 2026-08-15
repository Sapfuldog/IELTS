"""Mistakes becoming flashcards — and, just as important, not becoming them.

The grader is imperfect and the model occasionally "corrects" something that
was already right, so the restraint tested here is what keeps the card deck
from filling with noise.
"""
from __future__ import annotations

from app.services import mistakes


class TestGapAnswers:
    async def test_a_missed_word_becomes_a_card(self, database):
        question = {
            "type": "gap",
            "q": "The rate includes a continental ____.",
            "answer": "breakfast",
            "explanation": "The receptionist mentions a continental breakfast.",
        }
        assert await mistakes.from_gap_answer(database, 1, question, "dinner") is True

        card = (await database.due_cards(1))[0]
        assert card["word"] == "breakfast"
        assert card["learner_answer"] == "dinner"
        assert card["source"] == "gap"
        assert "continental" in card["context"]

    async def test_a_correct_answer_makes_no_card(self, database):
        question = {"type": "gap", "q": "?", "answer": "breakfast", "explanation": "e"}
        assert await mistakes.from_gap_answer(database, 1, question, "Breakfast") is False

    async def test_a_punctuation_only_difference_makes_no_card(self, database):
        """The grader accepts these, so they are not mistakes."""
        question = {"type": "gap", "q": "?", "answer": "water‑cooler", "explanation": "e"}
        assert await mistakes.from_gap_answer(database, 1, question, "water-cooler") is False

    async def test_a_blank_answer_still_teaches_the_word(self, database):
        question = {"type": "gap", "q": "?", "answer": "breakfast", "explanation": "e"}
        assert await mistakes.from_gap_answer(database, 1, question, "") is True

    async def test_a_whole_sentence_is_not_a_flashcard(self, database):
        question = {
            "type": "gap", "q": "?",
            "answer": "a considerable amount of time and effort",
            "explanation": "e",
        }
        assert await mistakes.from_gap_answer(database, 1, question, "x") is False

    async def test_a_single_character_is_not_a_flashcard(self, database):
        question = {"type": "gap", "q": "?", "answer": "a", "explanation": "e"}
        assert await mistakes.from_gap_answer(database, 1, question, "b") is False

    async def test_missing_the_same_word_twice_keeps_one_card(self, database):
        question = {"type": "gap", "q": "?", "answer": "breakfast", "explanation": "e"}
        await mistakes.from_gap_answer(database, 1, question, "dinner")
        assert await mistakes.from_gap_answer(database, 1, question, "lunch") is False
        assert (await database.card_counts(1))["total"] == 1


class TestCorrections:
    async def test_corrections_become_cards(self, database):
        created = await mistakes.from_corrections(
            database, 1,
            [
                {"wrong": "many people thinks", "right": "many people think",
                 "note": "plural subject takes a plural verb", "note_ru": "мн. число"},
                {"wrong": "recieve", "right": "receive",
                 "note": "i before e except after c", "note_ru": "правило ie/ei"},
            ],
            source="writing",
        )
        assert created == 2

        words = {c["word"] for c in await database.due_cards(1)}
        assert words == {"many people think", "receive"}

    async def test_the_rule_and_its_translation_are_kept(self, database):
        await mistakes.from_corrections(
            database, 1,
            [{"wrong": "recieve", "right": "receive",
              "note": "i before e except after c", "note_ru": "правило ie/ei"}],
            source="writing",
        )
        card = (await database.due_cards(1))[0]
        assert card["definition"] == "i before e except after c"
        assert card["translation"] == "правило ie/ei"
        assert card["learner_answer"] == "recieve"

    async def test_an_empty_correction_is_skipped(self, database):
        created = await mistakes.from_corrections(
            database, 1,
            [{"wrong": "", "right": "", "note": "", "note_ru": ""}],
            source="writing",
        )
        assert created == 0

    async def test_a_correction_that_changes_nothing_is_skipped(self, database):
        """The model sometimes 'corrects' text that was already right."""
        created = await mistakes.from_corrections(
            database, 1,
            [{"wrong": "receive", "right": "Receive", "note": "n", "note_ru": "н"}],
            source="writing",
        )
        assert created == 0

    async def test_a_rewritten_sentence_is_not_a_flashcard(self, database):
        created = await mistakes.from_corrections(
            database, 1,
            [{"wrong": "In my country the fee is very high",
              "right": "In my country the fees are very high and students cannot afford them",
              "note": "n", "note_ru": "н"}],
            source="writing",
        )
        assert created == 0

    async def test_no_corrections_is_not_an_error(self, database):
        assert await mistakes.from_corrections(database, 1, [], source="writing") == 0
        assert await mistakes.from_corrections(database, 1, None, source="writing") == 0

    async def test_writing_and_speaking_cards_are_separate(self, database):
        item = [{"wrong": "a", "right": "receive", "note": "n", "note_ru": "н"}]
        assert await mistakes.from_corrections(database, 1, item, source="writing") == 1
        assert await mistakes.from_corrections(database, 1, item, source="speaking") == 1
        assert (await database.card_counts(1))["from_mistakes"] == 2
