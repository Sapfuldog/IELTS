"""Shared fixtures and test doubles.

The doubles here deliberately enforce the limits the real services impose:
a message longer than Telegram accepts raises, and the agent refuses to reach
the network. Both failures happened for real and were invisible precisely
because the earlier throwaway stubs were more permissive than production.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Config  # noqa: E402
from app.formatting import TELEGRAM_LIMIT  # noqa: E402

_ALLOWED_TAGS = {"b", "i", "u", "s", "code", "pre", "a", "tg-spoiler", "blockquote"}


def assert_sendable(text: str) -> None:
    """Reject anything Telegram would reject."""
    if len(text) > TELEGRAM_LIMIT:
        raise AssertionError(
            f"message is {len(text)} characters, Telegram accepts {TELEGRAM_LIMIT}"
        )
    import re

    depth: list[str] = []
    for match in re.finditer(r"<(/?)([a-z-]+)[^>]*>", text):
        closing, tag = match.group(1), match.group(2)
        if tag not in _ALLOWED_TAGS:
            raise AssertionError(f"tag <{tag}> is not allowed in Telegram HTML")
        if closing:
            if not depth or depth.pop() != tag:
                raise AssertionError(f"</{tag}> does not close anything open")
        else:
            depth.append(tag)
    if depth:
        raise AssertionError(f"unclosed tags: {depth}")


class FakeMessage:
    """Stands in for aiogram's Message and records everything sent."""

    def __init__(self, chat_id: int = 1, text: str = ""):
        self.chat = type("Chat", (), {"id": chat_id})()
        self.text = text
        self.voice = None
        self.audio = None
        self.sent: list[str] = []

    async def answer(self, text: str, **kwargs):
        assert_sendable(text)
        self.sent.append(text)
        return self

    async def answer_voice(self, voice, caption=None, **kwargs):
        self.sent.append(f"<voice {len(voice.data)} bytes>")
        return self

    async def edit_text(self, text: str, **kwargs):
        assert_sendable(text)
        self.sent.append(text)
        return self

    async def delete(self):
        return True

    def joined(self) -> str:
        return "\n".join(self.sent)


class FakeCallback:
    def __init__(self, message: FakeMessage, data: str = ""):
        self.message = message
        self.data = data
        self.answered = False

    async def answer(self, *args, **kwargs):
        self.answered = True


@pytest.fixture
def message() -> FakeMessage:
    return FakeMessage()


@pytest.fixture
def offline_config() -> Config:
    """A config with no credentials, so nothing can reach the network."""
    return Config(
        bot_token="test:token",
        db_path=Path("test.db"),
        anthropic_api_key=None,
        anthropic_model="claude-sonnet-5",
        openrouter_api_key=None,
        openrouter_model="test/model",
        telegram_proxy=None,
    )


@pytest.fixture
def agent_config(offline_config: Config) -> Config:
    """A config that looks credentialled; pair it with a stubbed `_ask`."""
    return dataclasses.replace(offline_config, openrouter_api_key="sk-or-v1-test")


@pytest.fixture
async def database(tmp_path):
    from app.db import Database

    db = Database(tmp_path / "test.db")
    await db.init()
    return db
