"""Card storage: what gets added, what comes back due, and what must not
lose the learner's progress."""
from __future__ import annotations

import pytest


class TestAdding:
    async def test_a_new_card_is_created(self, database):
        assert await database.add_card(1, "ubiquitous", source="deck") is True

    async def test_the_same_word_from_the_same_source_is_not_duplicated(self, database):
        await database.add_card(1, "ubiquitous", source="deck")
        assert await database.add_card(1, "ubiquitous", source="deck") is False
        assert (await database.card_counts(1))["total"] == 1

    async def test_the_same_word_from_a_mistake_is_a_separate_card(self, database):
        """Meeting a word in a deck and missing it in a gap fill are different
        events and deserve separate scheduling."""
        await database.add_card(1, "ubiquitous", source="deck")
        assert await database.add_card(1, "ubiquitous", source="gap") is True
        assert (await database.card_counts(1))["total"] == 2

    async def test_cards_are_per_learner(self, database):
        await database.add_card(1, "ubiquitous", source="deck")
        assert await database.add_card(2, "ubiquitous", source="deck") is True

    async def test_mistake_context_is_kept(self, database):
        await database.add_card(
            1, "breakfast", source="gap", origin_id="l1",
            context="The rate includes a continental breakfast.",
            learner_answer="brekfast",
        )
        card = (await database.due_cards(1))[0]
        assert card["learner_answer"] == "brekfast"
        assert "continental" in card["context"]


class TestDueQueue:
    async def test_new_cards_are_due_immediately(self, database):
        await database.add_card(1, "word", source="deck")
        assert len(await database.due_cards(1)) == 1

    async def test_a_known_card_leaves_the_queue(self, database):
        await database.add_card(1, "word", source="deck")
        card = (await database.due_cards(1))[0]
        await database.record_review(card["id"], knew=True)
        assert await database.due_cards(1) == []

    async def test_a_missed_card_stays_in_the_queue(self, database):
        await database.add_card(1, "word", source="deck")
        card = (await database.due_cards(1))[0]
        await database.record_review(card["id"], knew=False)
        assert len(await database.due_cards(1)) == 1

    async def test_the_queue_is_capped(self, database):
        for i in range(30):
            await database.add_card(1, f"word{i}", source="deck")
        assert len(await database.due_cards(1, limit=10)) == 10

    async def test_dismissed_cards_disappear(self, database):
        await database.add_card(1, "typo", source="writing")
        card = (await database.due_cards(1))[0]
        await database.dismiss_card(card["id"])
        assert await database.due_cards(1) == []
        assert (await database.card_counts(1))["total"] == 0

    async def test_reviewing_a_missing_card_is_harmless(self, database):
        await database.record_review(999, knew=True)  # must not raise


class TestCounts:
    async def test_counts_separate_mistakes_from_decks(self, database):
        await database.add_card(1, "a", source="deck")
        await database.add_card(1, "b", source="gap")
        await database.add_card(1, "c", source="writing")
        counts = await database.card_counts(1)
        assert counts["total"] == 3
        assert counts["from_mistakes"] == 2

    async def test_learned_counts_only_established_cards(self, database):
        await database.add_card(1, "a", source="deck")
        card = (await database.due_cards(1))[0]
        for _ in range(3):
            await database.record_review(card["id"], knew=True)
        assert (await database.card_counts(1))["learned"] == 1

    async def test_empty_for_a_new_learner(self, database):
        assert await database.card_counts(99) == {
            "total": 0, "due": 0, "from_mistakes": 0, "learned": 0
        }
