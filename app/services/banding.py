"""Raw scores → IELTS band scores.

Listening and Reading are scored by counting correct answers out of 40 and
reading the total off a conversion table. Writing and Speaking are judged
against band descriptors instead, so they arrive here already as bands.

The tables below are the widely published indicative ones. Real exams are
equated per version, so an official paper can differ by half a band — these
are good enough to show a learner where they stand, and the bot presents them
as estimates, never as an official result.
"""
from __future__ import annotations

QUESTIONS_PER_SECTION = 40

# (minimum raw score out of 40, band). Checked high to low.
_LISTENING_TABLE: list[tuple[int, float]] = [
    (39, 9.0), (37, 8.5), (35, 8.0), (32, 7.5), (30, 7.0), (26, 6.5),
    (23, 6.0), (18, 5.5), (16, 5.0), (13, 4.5), (11, 4.0), (8, 3.5),
    (6, 3.0), (4, 2.5), (3, 2.0), (2, 1.5), (1, 1.0),
]

_READING_TABLE: list[tuple[int, float]] = [
    (39, 9.0), (37, 8.5), (35, 8.0), (33, 7.5), (30, 7.0), (27, 6.5),
    (23, 6.0), (19, 5.5), (15, 5.0), (13, 4.5), (10, 4.0), (8, 3.5),
    (6, 3.0), (4, 2.5), (3, 2.0), (2, 1.5), (1, 1.0),
]

_TABLES = {"listening": _LISTENING_TABLE, "reading": _READING_TABLE}


def round_band(value: float) -> float:
    """Round to the nearest half band, IELTS-style.

    A .25 fraction rounds up to .5 and a .75 rounds up to the next whole band;
    everything else goes to the nearest half. Python's own round() would give
    banker's rounding here, which is not what IELTS does.
    """
    if value < 0:
        raise ValueError("a band score cannot be negative")
    halves = value * 2
    rounded = int(halves) + (1 if halves - int(halves) >= 0.5 else 0)
    return min(rounded / 2, 9.0)


def raw_to_band(section: str, correct: int, total: int = QUESTIONS_PER_SECTION) -> float:
    """Convert correct answers to a band for Listening or Reading.

    Practice sets are rarely a full 40 questions, so a shorter set is scaled up
    to the 40-question scale first. That keeps a 6/8 exercise comparable to a
    30/40 paper, at the cost of being coarser — one question swings more.
    """
    table = _TABLES.get(section)
    if table is None:
        raise ValueError(f"{section!r} is not scored by conversion table")
    if total <= 0:
        raise ValueError("total must be positive")
    correct = max(0, min(correct, total))

    scaled = round(correct / total * QUESTIONS_PER_SECTION)
    for minimum, band in table:
        if scaled >= minimum:
            return band
    return 0.0


def overall_band(sections: dict[str, float]) -> float:
    """Average the four section bands, then round to the nearest half band."""
    if not sections:
        raise ValueError("need at least one section band")
    return round_band(sum(sections.values()) / len(sections))


def describe(band: float) -> str:
    """The official label for a band, for feedback messages.

    A half band sits between two descriptors, so it takes the label of the
    whole band below it — 6.5 is described as Competent, not Good. Rounding
    the other way would tell a candidate they are a band higher than the
    scale says.
    """
    labels = [
        (9, "Expert user — fully operational command of English."),
        (8, "Very good user — fully operational, with occasional inaccuracies."),
        (7, "Good user — handles complex language well, with occasional slips."),
        (6, "Competent user — effective command despite some inaccuracies."),
        (5, "Modest user — partial command, copes with overall meaning."),
        (4, "Limited user — basic competence in familiar situations."),
        (3, "Extremely limited user — conveys only general meaning."),
        (2, "Intermittent user — great difficulty understanding English."),
        (1, "Non-user — no real ability beyond isolated words."),
    ]
    for minimum, label in labels:
        if band >= minimum:
            return label
    return "Did not attempt the test."
