"""When a flashcard should next be shown.

A simplified SM-2. The original algorithm asks the learner to rate recall on a
six-point scale; that precision is wasted here, because a two-button card
("I knew it" / "I didn't") is the only thing a learner will actually answer
honestly on a phone. What matters is that intervals grow for words that stick
and collapse for words that do not — not the exact curve.

Kept free of database and aiogram imports so it can be reasoned about, and
tested, on its own.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# Ease bounds from SM-2. Below 1.3 intervals stop growing usefully; above 2.5
# a card that was merely recognised starts disappearing for months.
MIN_EASE = 1.3
MAX_EASE = 2.5
DEFAULT_EASE = 2.5

FIRST_INTERVAL = 1.0    # days, after the first success
SECOND_INTERVAL = 6.0   # days, after the second
MAX_INTERVAL = 365.0


@dataclass(frozen=True)
class Schedule:
    """The state of one card's scheduling."""

    interval_days: float = 0.0
    ease: float = DEFAULT_EASE
    streak: int = 0

    def next(self, knew: bool) -> "Schedule":
        """The schedule after one review."""
        if not knew:
            # Back to the start of the ladder, and slightly harder from now on.
            # The card stays due today: a word you just failed is exactly the
            # one worth seeing again this session.
            return Schedule(
                interval_days=0.0,
                ease=max(MIN_EASE, self.ease - 0.2),
                streak=0,
            )

        streak = self.streak + 1
        if streak == 1:
            interval = FIRST_INTERVAL
        elif streak == 2:
            interval = SECOND_INTERVAL
        else:
            interval = min(self.interval_days * self.ease, MAX_INTERVAL)
        return Schedule(
            interval_days=interval,
            ease=min(MAX_EASE, self.ease + 0.1),
            streak=streak,
        )

    def due_at(self, now: datetime | None = None) -> datetime:
        now = now or datetime.now(timezone.utc)
        return now + timedelta(days=self.interval_days)


def review(interval_days: float, ease: float, streak: int, knew: bool) -> Schedule:
    """Convenience wrapper for callers holding loose database columns."""
    return Schedule(interval_days, ease, streak).next(knew)
