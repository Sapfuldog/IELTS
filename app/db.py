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
