"""SQLite persistence for users and their practice results."""
from __future__ import annotations

from pathlib import Path

import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT,
    full_name   TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS results (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    section      TEXT NOT NULL,          -- reading | listening | writing | speaking | vocabulary
    exercise_id  TEXT,
    score        REAL,                   -- correct answers, or estimated band
    max_score    REAL,                   -- total questions (NULL for band-style)
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_results_user ON results(user_id);

-- Flashcards, whether they came from a vocabulary deck or from a mistake the
-- learner made. `source` records which, so a card can be traced back to the
-- exercise that produced it and mistake cards can be shown differently.
CREATE TABLE IF NOT EXISTS cards (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    word           TEXT NOT NULL,
    definition     TEXT,
    example        TEXT,
    translation    TEXT,
    source         TEXT NOT NULL,      -- deck | gap | writing | speaking
    origin_id      TEXT,               -- deck or exercise it came from
    context        TEXT,               -- the sentence the word appeared in
    learner_answer TEXT,               -- what they wrote, for mistake cards
    due_at         TEXT NOT NULL DEFAULT (datetime('now')),
    interval_days  REAL NOT NULL DEFAULT 0,
    ease           REAL NOT NULL DEFAULT 2.5,
    streak         INTEGER NOT NULL DEFAULT 0,
    reviews        INTEGER NOT NULL DEFAULT 0,
    dismissed      INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    -- One card per word per source: re-reading a deck must not duplicate it,
    -- but the same word missed in a gap fill is a genuinely different card.
    UNIQUE(user_id, word, source)
);

CREATE INDEX IF NOT EXISTS idx_cards_due ON cards(user_id, dismissed, due_at);

-- How each question actually performs. The validator checks that a question is
-- self-consistent and the key audit checks it against its own explanation;
-- neither can catch a key that is confidently, uniformly wrong. Learners can:
-- a question nobody ever gets right is far more likely to have a bad key than
-- to be hard.
CREATE TABLE IF NOT EXISTS question_stats (
    section      TEXT NOT NULL,
    exercise_id  TEXT NOT NULL,
    q_index      INTEGER NOT NULL,
    attempts     INTEGER NOT NULL DEFAULT 0,
    correct      INTEGER NOT NULL DEFAULT 0,
    updated_at   TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (section, exercise_id, q_index)
);
"""


class Database:
    def __init__(self, path: Path):
        self._path = str(path)

    async def init(self) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.executescript(_SCHEMA)
            await db.commit()

    async def upsert_user(self, user_id: int, username: str | None, full_name: str) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                INSERT INTO users (user_id, username, full_name)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    full_name = excluded.full_name
                """,
                (user_id, username, full_name),
            )
            await db.commit()

    async def save_result(
        self,
        user_id: int,
        section: str,
        exercise_id: str | None,
        score: float | None,
        max_score: float | None,
    ) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                INSERT INTO results (user_id, section, exercise_id, score, max_score)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, section, exercise_id, score, max_score),
            )
            await db.commit()

    # --- Flashcards -------------------------------------------------------

    async def add_card(
        self,
        user_id: int,
        word: str,
        *,
        source: str,
        definition: str | None = None,
        example: str | None = None,
        translation: str | None = None,
        origin_id: str | None = None,
        context: str | None = None,
        learner_answer: str | None = None,
    ) -> bool:
        """Add a card unless the learner already has this word from this source.

        Returns True when a card was created. Re-reviewing a deck must not
        reset progress, so an existing card is left exactly as it is.
        """
        async with aiosqlite.connect(self._path) as db:
            cursor = await db.execute(
                """
                INSERT OR IGNORE INTO cards
                    (user_id, word, definition, example, translation,
                     source, origin_id, context, learner_answer)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user_id, word.strip(), definition, example, translation,
                 source, origin_id, context, learner_answer),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def due_cards(self, user_id: int, limit: int = 20) -> list[dict]:
        """Cards to study now: overdue first, then ones never seen."""
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM cards
                WHERE user_id = ? AND dismissed = 0 AND due_at <= datetime('now')
                ORDER BY reviews = 0, due_at
                LIMIT ?
                """,
                (user_id, limit),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def record_review(self, card_id: int, knew: bool) -> None:
        """Move a card along its schedule after the learner answers."""
        from app.services.scheduling import review

        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT interval_days, ease, streak FROM cards WHERE id = ?",
                (card_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return
            schedule = review(row["interval_days"], row["ease"], row["streak"], knew)
            await db.execute(
                """
                UPDATE cards
                SET interval_days = ?, ease = ?, streak = ?,
                    reviews = reviews + 1,
                    due_at = datetime('now', ? || ' days')
                WHERE id = ?
                """,
                (schedule.interval_days, schedule.ease, schedule.streak,
                 f"+{schedule.interval_days}", card_id),
            )
            await db.commit()

    async def record_answer(
        self, section: str, exercise_id: str, q_index: int, correct: bool
    ) -> None:
        """Note how one question was answered, for the quality report."""
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                INSERT INTO question_stats
                    (section, exercise_id, q_index, attempts, correct)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(section, exercise_id, q_index) DO UPDATE SET
                    attempts = attempts + 1,
                    correct = correct + excluded.correct,
                    updated_at = datetime('now')
                """,
                (section, exercise_id, q_index, 1 if correct else 0),
            )
            await db.commit()

    async def question_stats(self, min_attempts: int = 1) -> list[dict]:
        """Per-question results, for anything with enough answers to judge."""
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT section, exercise_id, q_index, attempts, correct,
                       CAST(correct AS REAL) / attempts AS pass_rate
                FROM question_stats
                WHERE attempts >= ?
                ORDER BY pass_rate, attempts DESC
                """,
                (min_attempts,),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def all_words(self, user_id: int) -> list[dict]:
        """Every word the learner already holds, dismissed ones included.

        A card they retired should not come back through the random draw.
        """
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT word, source FROM cards WHERE user_id = ?", (user_id,)
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def dismiss_card(self, card_id: int) -> None:
        """Retire a card the learner says was a typo, not a gap in knowledge."""
        async with aiosqlite.connect(self._path) as db:
            await db.execute("UPDATE cards SET dismissed = 1 WHERE id = ?", (card_id,))
            await db.commit()

    async def card_counts(self, user_id: int) -> dict:
        """Totals for the progress screen."""
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT
                    COUNT(*)                                          AS total,
                    SUM(due_at <= datetime('now'))                    AS due,
                    SUM(source != 'deck')                             AS from_mistakes,
                    SUM(streak >= 3)                                  AS learned
                FROM cards
                WHERE user_id = ? AND dismissed = 0
                """,
                (user_id,),
            )
            row = await cursor.fetchone()
            return {k: (row[k] or 0) for k in ("total", "due", "from_mistakes", "learned")}

    async def stats_by_section(self, user_id: int) -> list[dict]:
        """Aggregate progress per section for one user."""
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT
                    section,
                    COUNT(*)                        AS attempts,
                    SUM(COALESCE(score, 0))         AS total_score,
                    SUM(COALESCE(max_score, 0))     AS total_max,
                    AVG(score)                      AS avg_score
                FROM results
                WHERE user_id = ?
                GROUP BY section
                ORDER BY section
                """,
                (user_id,),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def recent_results(self, user_id: int, limit: int = 5) -> list[dict]:
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT section, exercise_id, score, max_score, created_at
                FROM results
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, limit),
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
