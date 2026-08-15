"""Spot questions that are probably broken rather than merely hard.

Two checks already guard generated content: the validator proves a question is
self-consistent, and the key audit proves the key does not contradict its own
explanation. Neither can catch a key that is confidently, uniformly wrong —
the passage reads well, the explanation matches the option it names, and the
option named is simply not the right one.

Learners catch it. A question almost nobody answers correctly is far more
likely to have a bad key than to be difficult, and one everybody answers
correctly is measuring nothing. Both are worth a look; neither is proof.
"""
from __future__ import annotations

from dataclasses import dataclass

# Below this many answers the pass rate is noise: two learners guessing wrong
# says nothing, and flagging on it would bury the real cases.
MIN_ATTEMPTS = 5

# A question the whole cohort fails. Real IELTS items sit far above this even
# at band 8 — 10% suggests the key, not the difficulty.
BROKEN_BELOW = 0.10

# Everyone gets it right. Not wrong, but it separates nobody, so it costs a
# question slot without measuring anything.
TRIVIAL_ABOVE = 0.98


@dataclass(frozen=True)
class Flag:
    section: str
    exercise_id: str
    q_index: int
    attempts: int
    pass_rate: float
    reason: str

    @property
    def suspect_key(self) -> bool:
        return self.pass_rate <= BROKEN_BELOW

    def describe(self) -> str:
        return (
            f"{self.section}/{self.exercise_id} Q{self.q_index + 1}: "
            f"{self.pass_rate:.0%} of {self.attempts} answers correct — {self.reason}"
        )


def flag(stats: list[dict], min_attempts: int = MIN_ATTEMPTS) -> list[Flag]:
    """Pick out questions worth re-checking. Ordered worst first."""
    flags: list[Flag] = []
    for row in stats:
        if row["attempts"] < min_attempts:
            continue
        rate = row["pass_rate"]
        if rate <= BROKEN_BELOW:
            reason = "almost nobody gets this right, which usually means the key is wrong"
        elif rate >= TRIVIAL_ABOVE:
            reason = "everybody gets this right, so it distinguishes nobody"
        else:
            continue
        flags.append(
            Flag(
                section=row["section"],
                exercise_id=row["exercise_id"],
                q_index=row["q_index"],
                attempts=row["attempts"],
                pass_rate=rate,
                reason=reason,
            )
        )
    return sorted(flags, key=lambda f: f.pass_rate)
