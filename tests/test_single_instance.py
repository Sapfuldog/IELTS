"""The guard against two bots on one token.

Two instances both poll, Telegram hands each update to whichever asks first,
and the learner ends up talking to one of them at random. It happened three
times while this project was being built, and every time it looked like a
broken feature rather than a duplicate process.
"""
from __future__ import annotations

import os

import pytest

from app.main import AlreadyRunning, claim_single_instance


class TestClaiming:
    def test_a_free_lock_is_taken(self, tmp_path):
        lock = tmp_path / "bot.pid"
        claim_single_instance(lock)
        assert lock.read_text().strip() == str(os.getpid())

    def test_a_lock_held_by_a_live_process_is_refused(self, tmp_path):
        lock = tmp_path / "bot.pid"
        # PID 4 is the Windows System process and always exists; on POSIX the
        # test uses the parent, which is likewise alive.
        alive = 4 if os.name == "nt" else os.getppid()
        lock.write_text(str(alive))
        with pytest.raises(AlreadyRunning):
            claim_single_instance(lock)

    def test_a_stale_lock_is_reclaimed(self, tmp_path):
        """A killed bot leaves its file behind; that must not block a restart."""
        lock = tmp_path / "bot.pid"
        lock.write_text("999999")
        claim_single_instance(lock)
        assert lock.read_text().strip() == str(os.getpid())

    def test_a_corrupt_lock_is_reclaimed(self, tmp_path):
        lock = tmp_path / "bot.pid"
        lock.write_text("not a pid")
        claim_single_instance(lock)
        assert lock.read_text().strip() == str(os.getpid())

    def test_our_own_pid_does_not_block_us(self, tmp_path):
        lock = tmp_path / "bot.pid"
        lock.write_text(str(os.getpid()))
        claim_single_instance(lock)  # must not raise

    def test_the_directory_is_created(self, tmp_path):
        lock = tmp_path / "nested" / "bot.pid"
        claim_single_instance(lock)
        assert lock.exists()

    def test_the_message_names_the_holder(self, tmp_path):
        lock = tmp_path / "bot.pid"
        alive = 4 if os.name == "nt" else os.getppid()
        lock.write_text(str(alive))
        with pytest.raises(AlreadyRunning, match=str(alive)):
            claim_single_instance(lock)
