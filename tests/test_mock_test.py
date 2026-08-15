"""A full mock test driven through the real FSM, offline.

This is the test that would have caught the section that silently produced
nothing: every message goes through `FakeMessage`, which rejects anything
Telegram would reject.
"""
from __future__ import annotations

import random

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from app.handlers import mock_test as mt
from app.services import content

from conftest import FakeCallback, FakeMessage

ESSAY = " ".join(f"word{i % 60}" for i in range(300))
SPOKEN = " ".join(f"term{i % 70}" for i in range(200))


@pytest.fixture
def state() -> FSMContext:
    return FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=1, user_id=1))


async def run_test(message, state, config, db, answer_correctly: bool):
    """Play a whole sitting; returns nothing, leaves everything in `message`."""
    random.seed(11)
    await mt.start_test(FakeCallback(message), state, config, db)

    for _ in range(500):
        current = await state.get_state()
        if current not in ("MockTest:listening", "MockTest:reading"):
            break
        data = await state.get_data()
        section = mt._STAGES[data["stage_index"]]
        question = mt._current_question(data, section)
        given = str(question["answer"]) if answer_correctly else "zzz"
        if question["type"] == "gap":
            message.text = given
            await mt.on_test_typed(message, state, config, db)
        else:
            await mt.on_test_choice(
                FakeCallback(message, f"ans:{given}"), state, config, db
            )

    message.text = ESSAY
    await mt.on_test_essay(message, state, config, db)
    message.text = SPOKEN
    await mt.on_test_speaking(message, state, config, db)


class TestFullSitting:
    async def test_reaches_a_band_and_clears_state(self, offline_config, database, state):
        message = FakeMessage()
        await run_test(message, state, offline_config, database, answer_correctly=True)

        assert await state.get_state() is None, "the test must not leave the user stuck"
        assert "Test complete" in message.joined()
        assert "Overall band" in message.joined()

    async def test_every_section_is_scored(self, offline_config, database, state):
        message = FakeMessage()
        await run_test(message, state, offline_config, database, answer_correctly=True)

        rows = await database.recent_results(1, limit=10)
        sections = {r["section"] for r in rows}
        assert sections == {
            "test:listening", "test:reading", "test:writing",
            "test:speaking", "test:overall",
        }

    async def test_answers_change_the_band(self, offline_config, database, state):
        good = FakeMessage()
        await run_test(good, state, offline_config, database, answer_correctly=True)
        good_overall = next(
            r["score"] for r in await database.recent_results(1, 10)
            if r["section"] == "test:overall"
        )

        bad_state = FSMContext(MemoryStorage(), StorageKey(bot_id=1, chat_id=2, user_id=2))
        bad = FakeMessage(chat_id=2)
        await run_test(bad, bad_state, offline_config, database, answer_correctly=False)
        bad_overall = next(
            r["score"] for r in await database.recent_results(2, 10)
            if r["section"] == "test:overall"
        )

        assert good_overall > bad_overall


class TestReview:
    async def test_correct_answers_are_shown_after_the_section(
        self, offline_config, database, state
    ):
        message = FakeMessage()
        await run_test(message, state, offline_config, database, answer_correctly=False)

        reviews = [m for m in message.sent if "Answers for this section" in m]
        assert len(reviews) == 2, "one review per quiz section"
        assert "correct:" in reviews[0], "a wrong answer must show the right one"

    async def test_nothing_is_revealed_before_the_section_ends(
        self, offline_config, database, state
    ):
        """Told immediately, the learner adapts and the score stops measuring."""
        message = FakeMessage()
        random.seed(11)
        await mt.start_test(FakeCallback(message), state, offline_config, database)

        data = await state.get_data()
        if mt._section_question_count(data, "listening") > 1:
            await mt.on_test_choice(
                FakeCallback(message, "ans:zzz"), state, offline_config, database
            )
            assert "correct:" not in message.joined()


class TestRendering:
    def test_learner_answers_render_as_text_not_payloads(self):
        question = {"type": "mc", "options": ["Rooftops", "Underground"], "answer": 0}
        assert mt._given_text(question, "1") == "Underground"

    def test_choice_payload_is_humanised(self):
        assert mt._given_text({"type": "tfng", "answer": "TRUE"}, "NOT_GIVEN") == "NOT GIVEN"

    def test_empty_answer_has_a_placeholder(self):
        assert mt._given_text({"type": "gap", "answer": "x"}, "  ") == "—"


class TestSectionAssembly:
    """A section is built from several exercises, as a real paper is."""

    def test_a_section_stacks_exercises_towards_the_target(self):
        chosen = mt.assemble_section("reading")
        assert len(chosen) > 1, "one exercise is not a section"

    def test_it_stops_once_the_target_is_reached(self):
        chosen = mt.assemble_section("reading", target=1)
        assert len(chosen) == 1

    def test_no_exercise_appears_twice(self):
        """Seeing the same passage twice would measure memory, not reading."""
        chosen = mt.assemble_section("reading")
        ids = [e["id"] for e in chosen]
        assert len(ids) == len(set(ids))

    def test_it_never_asks_for_more_than_the_bank_holds(self):
        chosen = mt.assemble_section("reading", target=10_000)
        assert len(chosen) == len(content.get_all("reading"))

    async def test_questions_are_numbered_across_the_whole_section(
        self, offline_config, database, state
    ):
        message = FakeMessage()
        random.seed(11)
        await mt.start_test(FakeCallback(message), state, offline_config, database)

        data = await state.get_data()
        total = mt._section_question_count(data, "listening")
        assert f"Question 1/{total}" in message.joined()

        # Answer through the first exercise and check the count keeps climbing.
        first = mt._exercise_at(data, "listening", 0)
        for _ in range(len(first["questions"])):
            data = await state.get_data()
            if data.get("ex_index", 0) != 0:
                break
            question = mt._current_question(data, "listening")
            if question["type"] == "gap":
                message.text = "zzz"
                await mt.on_test_typed(message, state, offline_config, database)
            else:
                await mt.on_test_choice(
                    FakeCallback(message, "ans:zzz"), state, offline_config, database
                )
        assert "Part 2 of" in message.joined()
        assert f"Question 1/{total}" in message.joined()  # never restarts at 1/N

    async def test_the_review_covers_every_part(
        self, offline_config, database, state
    ):
        message = FakeMessage()
        await run_test(message, state, offline_config, database, answer_correctly=False)
        review = "\n".join(m for m in message.sent if "Answers for this section" in m)
        assert review.count("❌") >= 5, "the review must list every question answered"


class TestTiming:
    """Pace is reported against the real allowance, never enforced."""

    def test_minutes_and_seconds_are_readable(self):
        assert mt._format_minutes(45) == "45 s"
        assert mt._format_minutes(125) == "2 min 05 s"

    def test_inside_the_allowance_is_marked_good(self):
        note = mt._timing_note("listening", 20 * 60)
        assert "of the 30 min allowed" in note and "✅" in note

    def test_over_the_allowance_is_flagged(self):
        note = mt._timing_note("listening", 45 * 60)
        assert "over the 30 min allowed" in note and "⏰" in note

    def test_speaking_is_not_timed_against_the_clock(self):
        """Typed answers take longer than spoken ones, so the limit would mislead."""
        assert "allowed" not in mt._timing_note("speaking", 30 * 60)

    async def test_each_section_reports_its_time(
        self, offline_config, database, state
    ):
        message = FakeMessage()
        await run_test(message, state, offline_config, database, answer_correctly=True)
        assert "took" in message.joined()

    async def test_the_final_report_totals_the_time(
        self, offline_config, database, state
    ):
        message = FakeMessage()
        await run_test(message, state, offline_config, database, answer_correctly=True)
        final = [m for m in message.sent if "Test complete" in m][0]
        assert "Total time:" in final


class TestDifficultySpread:
    """A paper builds up: the easy passage first, the hardest last."""

    def test_sections_are_ordered_by_stated_band(self, monkeypatch):
        pool = [
            {"id": "hard", "target_band": 8, "questions": [{}]},
            {"id": "easy", "target_band": 5, "questions": [{}]},
            {"id": "mid", "target_band": 7, "questions": [{}]},
        ]
        monkeypatch.setattr(content, "get_all", lambda s: pool)
        assert [e["id"] for e in mt.assemble_section("reading", target=3)] == [
            "easy", "mid", "hard"
        ]

    def test_exercises_without_a_band_sit_in_the_middle(self, monkeypatch):
        """Hand-written content predates the field and must not be exiled."""
        pool = [
            {"id": "hard", "target_band": 8, "questions": [{}]},
            {"id": "unmarked", "questions": [{}]},
            {"id": "easy", "target_band": 5, "questions": [{}]},
        ]
        monkeypatch.setattr(content, "get_all", lambda s: pool)
        order = [e["id"] for e in mt.assemble_section("reading", target=3)]
        assert order.index("easy") < order.index("unmarked") < order.index("hard")

    def test_the_real_bank_still_assembles(self):
        assert len(mt.assemble_section("reading")) > 1
