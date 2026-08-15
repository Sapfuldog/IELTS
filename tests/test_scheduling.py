"""Spaced repetition: intervals must grow for words that stick and collapse
for words that do not."""
from __future__ import annotations

import pytest

from app.services.scheduling import (
    DEFAULT_EASE,
    MAX_EASE,
    MAX_INTERVAL,
    MIN_EASE,
    Schedule,
    review,
)


class TestSuccess:
    def test_first_success_is_tomorrow(self):
        assert Schedule().next(knew=True).interval_days == 1.0

    def test_second_success_is_next_week(self):
        after_one = Schedule().next(True)
        assert after_one.next(True).interval_days == 6.0

    def test_intervals_then_grow_by_ease(self):
        schedule = Schedule().next(True).next(True)   # 6 days
        grown = schedule.next(True)
        assert grown.interval_days == pytest.approx(6.0 * schedule.ease)
        assert grown.interval_days > 6.0

    def test_ease_rises_but_is_capped(self):
        schedule = Schedule(ease=MAX_EASE)
        assert schedule.next(True).ease == MAX_EASE

    def test_interval_is_capped_at_a_year(self):
        assert Schedule(interval_days=900, ease=2.5, streak=9).next(True).interval_days == MAX_INTERVAL


class TestFailure:
    def test_failure_makes_the_card_due_immediately(self):
        """A word you just missed is the one worth seeing again this session."""
        schedule = Schedule(interval_days=30, ease=2.5, streak=5)
        assert schedule.next(knew=False).interval_days == 0.0

    def test_failure_resets_the_streak(self):
        assert Schedule(streak=7).next(False).streak == 0

    def test_failure_lowers_ease(self):
        assert Schedule(ease=2.5).next(False).ease == pytest.approx(2.3)

    def test_ease_has_a_floor(self):
        schedule = Schedule(ease=MIN_EASE)
        assert schedule.next(False).ease == MIN_EASE

    def test_a_hard_word_stays_frequent(self):
        """Repeated failure must not let a card drift out of rotation."""
        schedule = Schedule()
        for _ in range(5):
            schedule = schedule.next(False)
        assert schedule.interval_days == 0.0
        assert schedule.ease < DEFAULT_EASE

    def test_ease_never_falls_below_the_floor(self):
        schedule = Schedule()
        for _ in range(20):
            schedule = schedule.next(False)
        assert schedule.ease == MIN_EASE


class TestRecovery:
    def test_relearning_climbs_the_ladder_again(self):
        schedule = Schedule(interval_days=30, ease=2.5, streak=5).next(False)
        assert schedule.next(True).interval_days == 1.0
        assert schedule.next(True).next(True).interval_days == 6.0

    def test_lowered_ease_persists_through_relearning(self):
        """A word that was once forgotten should come back more often than one
        that never was."""
        forgotten = Schedule(interval_days=30, ease=2.5, streak=5).next(False)
        never_missed = Schedule(ease=DEFAULT_EASE)
        assert forgotten.ease < never_missed.ease


class TestWrapper:
    def test_review_matches_the_dataclass(self):
        assert review(6.0, 2.5, 2, True) == Schedule(6.0, 2.5, 2).next(True)

    def test_due_at_moves_forward_by_the_interval(self):
        from datetime import datetime, timezone

        now = datetime(2026, 8, 15, tzinfo=timezone.utc)
        due = Schedule(interval_days=6.0).due_at(now)
        assert (due - now).days == 6
